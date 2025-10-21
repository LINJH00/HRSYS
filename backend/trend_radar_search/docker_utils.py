import subprocess
import time
from typing import List
from pathlib import Path
import sys
import threading
import shutil
from subprocess import CalledProcessError
import requests

# Use pathlib for robust imports
current_dir = Path(__file__).parent
backend_dir = current_dir.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(current_dir))

from backend import config
import search as search_mod

# Internal counter for searxng searches
_SEARCH_COUNT = 0

# Container status cache to avoid frequent shell command executions
_LAST_CHECK_TIME = 0
_LAST_CHECK_STATUS = None
_CHECK_INTERVAL = 60  # 检查容器状态的间隔（1分钟），避免频繁shell调用

# Concurrency primitives to coordinate counting and restarts
_STATE_LOCK = threading.Lock()
_RESTART_COND = threading.Condition(_STATE_LOCK)
_RESTARTING = False


def check_containers(force_check=False):
    """
    Check if the containers are running. And check status of searxng.
    Return "RESTART" if searxng is stopped.
    Return "START" if searxng is not found.
    Return "OK" if searxng is running.
    
    Now with caching to avoid frequent shell command executions.
    """
    global _LAST_CHECK_TIME, _LAST_CHECK_STATUS
    import time
    
    # 使用缓存避免频繁检查
    now = time.time()
    if not force_check and _LAST_CHECK_STATUS is not None:
        if (now - _LAST_CHECK_TIME) < _CHECK_INTERVAL:
            return _LAST_CHECK_STATUS
    
    # If docker is not available (e.g., inside single-container deployment), check supervisor services
    if shutil.which("docker") is None:
        try:
            # Consider RUNNING as healthy; anything else triggers restart
            cp = subprocess.run(
                "supervisorctl status searxng | grep RUNNING",
                shell=True,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if cp.returncode == 0:
                return "OK"
            return "RESTART"
        except Exception as e:
            print(f"[docker_utils] supervisor check error: {e}")
            return "RESTART"
    searx = getattr(config, 'SEARXNG_CONTAINER', 'searxng')
    valkey = getattr(config, 'VALKEY_CONTAINER', 'valkey')
    net = getattr(config, 'DOCKER_NETWORK', 'searx-net')
    cfg_path = getattr(config, 'DOCKER_CONFIG_PATH', '')
    cmds = [
        f"docker ps -a | grep {searx}",
        f"docker ps -a | grep {valkey}",
        f"docker network ls | grep {net}",
    ]
    for cmd in cmds:
        try:
            cp = subprocess.run(cmd, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if cp.returncode != 0:
                return "RESTART"
        except Exception as e:
            print(f"[docker_utils] Error checking containers: {e}")
            return "RESTART"
        
    cmd = f"docker ps -a | grep {searx} | grep Up"
    try:
        cp = subprocess.run(cmd, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if cp.returncode != 0:
            _LAST_CHECK_TIME = now
            _LAST_CHECK_STATUS = "RESTART"
            return "RESTART"
    except Exception:
        _LAST_CHECK_TIME = now
        _LAST_CHECK_STATUS = "RESTART"
        return "RESTART"
    
    _LAST_CHECK_TIME = now
    _LAST_CHECK_STATUS = "OK"
    return "OK"

def wait_for_searxng_ready(timeout: int = 30, check_interval: float = 2.0):
    """
    等待 SearXNG 完全启动并可以响应请求
    
    Args:
        timeout: 最大等待时间（秒）
        check_interval: 检查间隔（秒）
    
    Returns:
        True if ready, False if timeout
    """
    base_url = getattr(config, 'SEARXNG_BASE_URL', 'http://localhost:8888')
    start_time = time.time()
    
    print(f"[docker_utils] Waiting for SearXNG at {base_url} to be ready...")
    
    while (time.time() - start_time) < timeout:
        try:
            # 尝试访问 SearXNG 主页
            response = requests.get(base_url, timeout=5)
            if response.status_code == 200 and 'SearXNG' in response.text:
                elapsed = time.time() - start_time
                print(f"[docker_utils] SearXNG is ready! (took {elapsed:.1f}s)")
                return True
        except Exception:
            # 连接失败是正常的，继续等待
            pass
        
        time.sleep(check_interval)
    
    print(f"[docker_utils] WARNING: SearXNG not ready after {timeout}s timeout")
    return False

def run_search(query: str, pages: int = config.SEARXNG_PAGES, k_per_query: int = config.SEARCH_K, search_engines: List[str] = config.SEARXNG_ENGINES):
    """One search via searxng, with power-cycle counting."""
    global _SEARCH_COUNT, _RESTARTING

    # If a restart is in progress, wait until it completes
    with _RESTART_COND:
        while _RESTARTING:
            _RESTART_COND.wait()

    # Ensure containers are up; coordinate a single thread to start/restart if needed
    check_status = check_containers()
    if check_status in ("START", "RESTART"):
        should_act = False
        action = check_status  # "START" -> start_containers, "RESTART" -> restart_containers
        with _RESTART_COND:
            if not _RESTARTING:
                _RESTARTING = True
                should_act = True
        if should_act:
            try:
                if action == "START":
                    print(f"[docker_utils] Containers are not running, starting containers...")
                    start_containers()
                else:
                    print(f"[docker_utils] Containers not healthy, restarting containers...")
                    restart_containers()
                # 智能等待 SearXNG 完全启动（增加超时到 20 秒）
                wait_for_searxng_ready(timeout=20, check_interval=2.0)
            finally:
                with _RESTART_COND:
                    _RESTARTING = False
                    _RESTART_COND.notify_all()
        else:
            # Another thread is starting/restarting; wait
            with _RESTART_COND:
                while _RESTARTING:
                    _RESTART_COND.wait()

    # Perform the search without holding locks to allow concurrency
    res = search_mod.searxng_search(query=query, engines=search_engines, pages=pages, k_per_query=k_per_query)

    # Update counter atomically and decide if we need to restart
    trigger_restart = False
    with _RESTART_COND:
        _SEARCH_COUNT += 1
        limit = getattr(config, 'POWER_CYCLE_MAX_SEARCHES', 1000)
        if _SEARCH_COUNT >= limit and not _RESTARTING:
            _RESTARTING = True
            trigger_restart = True

    if trigger_restart:
        print(f"[docker_utils] Reached {_SEARCH_COUNT} searches, restarting containers...")
        try:
            restart_containers()
            # 智能等待 SearXNG 完全启动（增加超时到 20 秒）
            wait_for_searxng_ready(timeout=20, check_interval=2.0)
        finally:
            with _RESTART_COND:
                _SEARCH_COUNT = 0
                _RESTARTING = False
                _RESTART_COND.notify_all()

    return res

def start_containers():
    """Start the containers."""
    global _LAST_CHECK_TIME, _LAST_CHECK_STATUS
    if shutil.which("docker") is None:
        # Single-container mode: start services via supervisor
        cmds = [
            "supervisorctl start redis",
            "supervisorctl start searxng",
        ]
        for cmd in cmds:
            try:
                print(f"[docker_utils] {cmd}")
                subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except CalledProcessError as e:
                print(f"[docker_utils] supervisor start error: {e}")
        # 更新缓存，避免立即重新检查
        _LAST_CHECK_TIME = time.time()
        _LAST_CHECK_STATUS = "OK"
        return
    searx = getattr(config, 'SEARXNG_CONTAINER', 'searxng')
    valkey = getattr(config, 'VALKEY_CONTAINER', 'valkey')
    net = getattr(config, 'DOCKER_NETWORK', 'searx-net')
    cfg_path = getattr(config, 'DOCKER_CONFIG_PATH', '')

    cmds2 = [
        f"docker network create {net}",
        f"docker run -d --name {valkey} --network {net} --restart unless-stopped valkey/valkey:latest",
        (
            f"docker run -d --name {searx} "
            f"--network {net} -p 8888:8080 "
            f"-v \"{cfg_path}/config/:/etc/searxng/:ro\" "
            f"-v \"{cfg_path}/data/:/var/cache/searxng/\" "
            "-e SEARXNG_LIMITER=0 "
            "-e SEARXNG_PUBLIC_INSTANCE=false "
            "-e SEARXNG_BASE_URL=\"http://localhost:8888/\" "
            "-e SEARXNG_REDIS_URL=\"redis://valkey:6379/0\" "
            "--ulimit nofile=65535:65535 "
            "docker.io/searxng/searxng:latest"
        ).format(searx=searx)
    ]
    for cmd in cmds2:
        try:
            print(f"[docker_utils] {cmd}")
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"[docker_utils] Error creating containers: {e}")
    
    # 更新缓存，避免立即重新检查
    _LAST_CHECK_TIME = time.time()
    _LAST_CHECK_STATUS = "OK"

def restart_containers():
    """Stop and remove containers, then recreate network and launch SearXNG+Valkey."""
    global _LAST_CHECK_TIME, _LAST_CHECK_STATUS
    if shutil.which("docker") is None:
        # Single-container mode: restart services via supervisor
        cmds = [
            "supervisorctl restart redis",
            "supervisorctl restart searxng",
        ]
        for cmd in cmds:
            try:
                print(f"[docker_utils] {cmd}")
                subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except CalledProcessError as e:
                print(f"[docker_utils] supervisor restart error: {e}")
        # 更新缓存，避免立即重新检查
        _LAST_CHECK_TIME = time.time()
        _LAST_CHECK_STATUS = "OK"
        return
    searx = getattr(config, 'SEARXNG_CONTAINER', 'searxng')
    valkey = getattr(config, 'VALKEY_CONTAINER', 'valkey')
    net = getattr(config, 'DOCKER_NETWORK', 'searx-net')
    cfg_path = getattr(config, 'DOCKER_CONFIG_PATH', '')

    cmds = [
        f"docker stop {searx}",
        f"docker stop {valkey}",
        f"docker rm {searx}",
        f"docker rm {valkey}",
        f"docker network rm {net}",
    ]
    for cmd in cmds:
        try:
            print(f"[docker_utils] {cmd}")
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"[docker_utils] Non-fatal: {e}")

    cmds2 = [
        f"docker network create {net}",
        f"docker run -d --name {valkey} --network {net} --restart unless-stopped valkey/valkey:latest",
        (
            f"docker run -d --name {searx} "
            f"--network {net} -p 8888:8080 "
            f"-v \"{cfg_path}/config/:/etc/searxng/:ro\" "
            f"-v \"{cfg_path}/data/:/var/cache/searxng/\" "
            "-e SEARXNG_LIMITER=0 "
            "-e SEARXNG_PUBLIC_INSTANCE=false "
            "-e SEARXNG_BASE_URL=\"http://localhost:8888/\" "
            "-e SEARXNG_REDIS_URL=\"redis://valkey:6379/0\" "
            "--ulimit nofile=65535:65535 "
            "docker.io/searxng/searxng:latest"
        ).format(searx=searx)
    ]
    for cmd in cmds2:
        try:
            print(f"[docker_utils] {cmd}")
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f"[docker_utils] Error creating containers: {e}")
    
    # 更新缓存，避免立即重新检查
    _LAST_CHECK_TIME = time.time()
    _LAST_CHECK_STATUS = "OK"

def search_with_restart(queries: List[str]):
    """Search a list of queries, auto power-cycle after threshold."""
    results_all = []
    for q in queries:
        try:
            results = run_search(q)
            results_all.extend(results)
        except Exception as e:
            print(f"[docker_utils] search error for {q}: {e}")
    return results_all




