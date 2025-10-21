"""
Task Manager for Incremental Search
Handles task state persistence and recovery
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import sys

# Add module path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

import schemas


# Task storage directory
TASK_DIR = Path(__file__).parent.parent.parent / "data" / "search_tasks"
TASK_DIR.mkdir(parents=True, exist_ok=True)

# Task expiration time (24 hours)
TASK_EXPIRATION_HOURS = 24


def generate_task_id() -> str:
    """Generate a unique task ID"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"task_{timestamp}_{unique_id}"


def _get_task_path(task_id: str) -> Path:
    """Get the file path for a task"""
    return TASK_DIR / f"{task_id}.json"


def save_task_state(state: schemas.SearchTaskState) -> bool:
    """
    Save task state to disk using JSON
    
    Args:
        state: SearchTaskState to save
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Update timestamp
        state.updated_at = time.time()
        
        # ✅ Debug: print state before saving
        print(f"[TaskManager] Preparing to save state:")
        print(f"[TaskManager]   - candidates_accum keys: {list(state.candidates_accum.keys())}")
        print(f"[TaskManager]   - all_scored_papers count: {len(state.all_scored_papers)}")
        print(f"[TaskManager]   - search_candidate_set count: {len(state.search_candidate_set)}")
        
        # Convert to dict for JSON serialization
        state_dict = {
            "task_id": state.task_id,
            "spec": state.spec.model_dump(),
            "pos": state.pos,
            "terms": state.terms,
            "rounds_completed": state.rounds_completed,
            "candidates_accum": {
                name: candidate.model_dump(by_alias=True) 
                for name, candidate in state.candidates_accum.items()
            },
            "all_serp": state.all_serp,
            "sources": state.sources,
            "all_scored_papers": {
                url: paper.model_dump() 
                for url, paper in state.all_scored_papers.items()
            },
            "search_candidate_set": state.search_candidate_set,
            "selected_urls_set": list(state.selected_urls_set),
            "selected_serp_url_set": list(state.selected_serp_url_set),
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }
        
        print(f"[TaskManager] State dict created, candidates_accum keys: {list(state_dict['candidates_accum'].keys())}")
        
        # Save to JSON file
        task_path = _get_task_path(state.task_id).with_suffix('.json')
        with open(task_path, 'w', encoding='utf-8') as f:
            json.dump(state_dict, f, ensure_ascii=False, indent=2)
        
        print(f"[TaskManager] Saved task state: {state.task_id}")
        print(f"[TaskManager]   - Rounds completed: {state.rounds_completed}")
        print(f"[TaskManager]   - Candidates found: {len(state.candidates_accum)}")
        print(f"[TaskManager]   - Search position: {state.pos}/{len(state.terms)}")
        
        return True
    except Exception as e:
        print(f"[TaskManager] Error saving task state: {e}")
        import traceback
        traceback.print_exc()
        return False


def load_task_state(task_id: str) -> Optional[schemas.SearchTaskState]:
    """
    Load task state from disk
    
    Args:
        task_id: Task ID to load
        
    Returns:
        SearchTaskState if found and valid, None otherwise
    """
    try:
        # Try JSON file first
        task_path = _get_task_path(task_id).with_suffix('.json')
        
        if not task_path.exists():
            print(f"[TaskManager] Task not found: {task_id}")
            return None
        
        # Check if task is expired
        file_mtime = task_path.stat().st_mtime
        if time.time() - file_mtime > TASK_EXPIRATION_HOURS * 3600:
            print(f"[TaskManager] Task expired: {task_id}")
            # Clean up expired task
            task_path.unlink(missing_ok=True)
            return None
        
        # Load from JSON
        with open(task_path, 'r', encoding='utf-8') as f:
            state_dict = json.load(f)
        
        # ✅ Debug: print loaded data
        print(f"[TaskManager] Loaded JSON, reconstructing objects...")
        print(f"[TaskManager]   - candidates_accum keys in JSON: {list(state_dict['candidates_accum'].keys())}")
        print(f"[TaskManager]   - all_scored_papers count in JSON: {len(state_dict['all_scored_papers'])}")
        
        # Reconstruct objects from dicts
        state = schemas.SearchTaskState(
            task_id=state_dict["task_id"],
            spec=schemas.QuerySpec(**state_dict["spec"]),
            pos=state_dict["pos"],
            terms=state_dict["terms"],
            rounds_completed=state_dict["rounds_completed"],
            candidates_accum={
                name: schemas.CandidateOverview(**cand_dict)
                for name, cand_dict in state_dict["candidates_accum"].items()
            },
            all_serp=state_dict["all_serp"],
            sources=state_dict["sources"],
            all_scored_papers={
                url: schemas.PaperWithScore(**paper_dict)
                for url, paper_dict in state_dict["all_scored_papers"].items()
            },
            search_candidate_set=state_dict["search_candidate_set"],
            selected_urls_set=set(state_dict["selected_urls_set"]),
            selected_serp_url_set=set(state_dict["selected_serp_url_set"]),
            created_at=state_dict["created_at"],
            updated_at=state_dict["updated_at"],
        )
        
        print(f"[TaskManager] State object created, candidates_accum: {len(state.candidates_accum)}")
        
        print(f"[TaskManager] Loaded task state: {task_id}")
        print(f"[TaskManager]   - Rounds completed: {state.rounds_completed}")
        print(f"[TaskManager]   - Candidates found: {len(state.candidates_accum)}")
        print(f"[TaskManager]   - Search position: {state.pos}/{len(state.terms)}")
        
        return state
    except Exception as e:
        print(f"[TaskManager] Error loading task state: {e}")
        import traceback
        traceback.print_exc()
        return None


def delete_task_state(task_id: str) -> bool:
    """
    Delete task state from disk
    
    Args:
        task_id: Task ID to delete
        
    Returns:
        True if successful, False otherwise
    """
    try:
        task_path = _get_task_path(task_id)
        if task_path.exists():
            task_path.unlink()
            print(f"[TaskManager] Deleted task: {task_id}")
            return True
        return False
    except Exception as e:
        print(f"[TaskManager] Error deleting task: {e}")
        return False


def cleanup_expired_tasks() -> int:
    """
    Clean up expired task files
    
    Returns:
        Number of tasks cleaned up
    """
    try:
        count = 0
        current_time = time.time()
        expiration_threshold = TASK_EXPIRATION_HOURS * 3600
        
        for task_file in TASK_DIR.glob("task_*.json"):
            file_mtime = task_file.stat().st_mtime
            if current_time - file_mtime > expiration_threshold:
                task_file.unlink()
                count += 1
                print(f"[TaskManager] Cleaned up expired task: {task_file.stem}")
        
        if count > 0:
            print(f"[TaskManager] Cleaned up {count} expired task(s)")
        
        return count
    except Exception as e:
        print(f"[TaskManager] Error during cleanup: {e}")
        return 0


def list_active_tasks() -> list:
    """
    List all active (non-expired) tasks
    
    Returns:
        List of task IDs
    """
    try:
        tasks = []
        current_time = time.time()
        expiration_threshold = TASK_EXPIRATION_HOURS * 3600
        
        for task_file in TASK_DIR.glob("task_*.json"):
            file_mtime = task_file.stat().st_mtime
            if current_time - file_mtime <= expiration_threshold:
                tasks.append(task_file.stem)
        
        return tasks
    except Exception as e:
        print(f"[TaskManager] Error listing tasks: {e}")
        return []


def create_task_state_from_spec(
    spec: schemas.QuerySpec,
    terms: list,
) -> schemas.SearchTaskState:
    """
    Create a new task state from a query specification
    
    Args:
        spec: Query specification
        terms: Search terms to use
        
    Returns:
        New SearchTaskState
    """
    task_id = generate_task_id()
    
    state = schemas.SearchTaskState(
        task_id=task_id,
        spec=spec,
        pos=0,
        terms=terms,
        rounds_completed=0,
        candidates_accum={},
        all_serp=[],
        sources={},
        all_scored_papers={},
        search_candidate_set=[],
        selected_urls_set=set(),
        selected_serp_url_set=set(),
    )
    
    return state

