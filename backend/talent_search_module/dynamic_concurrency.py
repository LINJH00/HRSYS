"""
Dynamic Concurrency Manager for Talent Search System
Intelligently adjusts thread pool sizes based on system resources and task characteristics
"""

import os
import psutil
import threading
from typing import Optional, Literal
from enum import Enum

class TaskType(Enum):
    """Task types with different concurrency characteristics"""
    IO_BOUND = "io_bound"          # Network requests, file I/O
    CPU_BOUND = "cpu_bound"         # LLM processing, parsing
    MIXED = "mixed"                 # Both IO and CPU
    LIGHTWEIGHT = "lightweight"     # Quick operations

class DynamicConcurrencyManager:
    """
    Manages optimal concurrency levels based on system resources and task type
    """
    
    def __init__(self):
        # System info
        self.cpu_count = os.cpu_count() or 4
        self.total_memory_gb = psutil.virtual_memory().total / (1024**3)
        
        # Track current usage
        self._lock = threading.Lock()
        self._active_workers = {}  # task_type -> count
        
        # Baseline limits
        self.min_workers = 2
        self.max_workers_io = min(100, self.cpu_count * 10)  # IO can be much higher
        self.max_workers_cpu = self.cpu_count + 2  # CPU bound should be close to core count
        self.max_workers_mixed = self.cpu_count * 3
        
        print(f"[DynamicConcurrency] Initialized: {self.cpu_count} CPUs, {self.total_memory_gb:.1f}GB RAM")
    
    def get_optimal_workers(
        self,
        task_count: int,
        task_type: TaskType = TaskType.MIXED,
        prefer_speed: bool = True,
        memory_per_task_mb: int = 500
    ) -> int:
        """
        Calculate optimal number of workers for given task
        
        Args:
            task_count: Number of tasks to process
            task_type: Type of task (IO_BOUND, CPU_BOUND, MIXED, LIGHTWEIGHT)
            prefer_speed: If True, prioritize speed over resource conservation
            memory_per_task_mb: Estimated memory per task in MB
            
        Returns:
            Optimal number of workers
        """
        
        # 1. Get current system state
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory_percent = psutil.virtual_memory().percent
        
        # 2. Base calculation based on task type
        if task_type == TaskType.IO_BOUND:
            # IO-bound can have many threads
            base_workers = min(task_count, self.cpu_count * 5)
            max_allowed = self.max_workers_io
            
        elif task_type == TaskType.CPU_BOUND:
            # CPU-bound should match CPU cores
            base_workers = min(task_count, self.cpu_count)
            max_allowed = self.max_workers_cpu
            
        elif task_type == TaskType.LIGHTWEIGHT:
            # Lightweight tasks can have more concurrency
            base_workers = min(task_count, self.cpu_count * 8)
            max_allowed = self.max_workers_io
            
        else:  # MIXED
            # Mixed workload: balance between IO and CPU
            base_workers = min(task_count, self.cpu_count * 2)
            max_allowed = self.max_workers_mixed
        
        # 3. Adjust based on current system load
        if cpu_percent > 80:
            # High CPU usage: reduce workers
            adjustment_factor = 0.6 if task_type == TaskType.CPU_BOUND else 0.8
            
        elif cpu_percent > 60:
            # Moderate CPU usage: slight reduction
            adjustment_factor = 0.8 if task_type == TaskType.CPU_BOUND else 0.9
            
        elif cpu_percent < 30:
            # Low CPU usage: can increase workers
            adjustment_factor = 1.5 if prefer_speed else 1.2
            
        else:
            # Normal range
            adjustment_factor = 1.0
        
        # 4. Memory constraint check
        available_memory_gb = psutil.virtual_memory().available / (1024**3)
        memory_constrained_workers = int(
            (available_memory_gb * 1024 * 0.8) / memory_per_task_mb
        )
        
        # 5. Calculate final worker count
        adjusted_workers = int(base_workers * adjustment_factor)
        
        # Apply all constraints
        optimal = max(
            self.min_workers,
            min(
                adjusted_workers,
                memory_constrained_workers,
                max_allowed,
                task_count  # Never more workers than tasks
            )
        )
        
        # 6. Log decision
        print(f"[DynamicConcurrency] Optimal workers: {optimal}")
        print(f"  Task: {task_count} {task_type.value} tasks")
        print(f"  System: CPU={cpu_percent:.1f}%, MEM={memory_percent:.1f}%")
        print(f"  Decision: base={base_workers}, adjusted={adjusted_workers}, final={optimal}")
        
        return optimal
    
    def get_candidate_processing_workers(
        self, 
        candidate_count: int,
        required_count: int,
        has_homepage: bool = True
    ) -> int:
        """
        Specialized calculation for candidate processing
        
        Args:
            candidate_count: Total number of candidates to process
            required_count: Number of candidates actually needed
            has_homepage: Whether candidates have homepages (more IO-intensive)
            
        Returns:
            Optimal worker count for candidate processing
        """
        
        # Candidate processing is MIXED: IO (web crawling) + CPU (LLM)
        # If processing homepages, more IO-bound
        task_type = TaskType.IO_BOUND if has_homepage else TaskType.MIXED
        
        # Memory estimate: each candidate with homepage uses ~1GB during processing
        memory_per_task = 1000 if has_homepage else 500
        
        # Smart strategy: process more than needed but not all
        smart_count = min(
            candidate_count,
            max(required_count * 2, required_count + 3)  # Process 2x or +3 extra
        )
        
        return self.get_optimal_workers(
            task_count=smart_count,
            task_type=task_type,
            prefer_speed=True,  # Users are waiting
            memory_per_task_mb=memory_per_task
        )
    
    def get_extraction_workers(self, url_count: int) -> int:
        """
        Optimal workers for URL content extraction
        
        Args:
            url_count: Number of URLs to fetch
            
        Returns:
            Optimal worker count
        """
        # URL fetching is IO-bound
        return self.get_optimal_workers(
            task_count=url_count,
            task_type=TaskType.IO_BOUND,
            prefer_speed=True,
            memory_per_task_mb=50  # URL fetching uses little memory
        )
    
    def get_llm_processing_workers(self, task_count: int) -> int:
        """
        Optimal workers for LLM processing tasks
        
        Args:
            task_count: Number of LLM calls to make
            
        Returns:
            Optimal worker count
        """
        # LLM processing is CPU-bound (and API rate limited)
        return self.get_optimal_workers(
            task_count=task_count,
            task_type=TaskType.CPU_BOUND,
            prefer_speed=True,
            memory_per_task_mb=200  # LLM prompts use moderate memory
        )
    
    def register_active_task(self, task_type: TaskType, count: int):
        """Register active workers (for monitoring)"""
        with self._lock:
            self._active_workers[task_type] = count
    
    def unregister_active_task(self, task_type: TaskType):
        """Unregister completed task"""
        with self._lock:
            self._active_workers.pop(task_type, None)
    
    def get_system_status(self) -> dict:
        """Get current system status"""
        return {
            "cpu_count": self.cpu_count,
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_available_gb": psutil.virtual_memory().available / (1024**3),
            "active_workers": dict(self._active_workers)
        }

# Global instance
_manager = None

def get_manager() -> DynamicConcurrencyManager:
    """Get or create the global concurrency manager"""
    global _manager
    if _manager is None:
        _manager = DynamicConcurrencyManager()
    return _manager

# Convenience functions
def get_optimal_workers(
    task_count: int,
    task_type: str = "mixed",
    **kwargs
) -> int:
    """
    Quick helper to get optimal worker count
    
    Args:
        task_count: Number of tasks
        task_type: One of 'io_bound', 'cpu_bound', 'mixed', 'lightweight'
        **kwargs: Additional parameters for get_optimal_workers
        
    Returns:
        Optimal number of workers
    """
    type_map = {
        'io_bound': TaskType.IO_BOUND,
        'io': TaskType.IO_BOUND,
        'cpu_bound': TaskType.CPU_BOUND,
        'cpu': TaskType.CPU_BOUND,
        'mixed': TaskType.MIXED,
        'lightweight': TaskType.LIGHTWEIGHT,
        'light': TaskType.LIGHTWEIGHT
    }
    
    task_type_enum = type_map.get(task_type.lower(), TaskType.MIXED)
    manager = get_manager()
    
    return manager.get_optimal_workers(task_count, task_type_enum, **kwargs)

# Specific helpers for common tasks
def get_candidate_workers(candidates: int, required: int) -> int:
    """Get optimal workers for candidate processing"""
    manager = get_manager()
    return manager.get_candidate_processing_workers(candidates, required)

def get_extraction_workers(urls: int) -> int:
    """Get optimal workers for URL extraction"""
    manager = get_manager()
    return manager.get_extraction_workers(urls)

def get_llm_workers(tasks: int) -> int:
    """Get optimal workers for LLM processing"""
    manager = get_manager()
    return manager.get_llm_processing_workers(tasks)
