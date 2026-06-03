# Copyright (C) 2026 humanity687
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Scheduler - EventBroadcaster, scheduled task execution, active task tracking
"""

import os
import json
import queue
import sys
import threading
import uuid
import time
from datetime import datetime

from src import state


class EventBroadcaster:
    def __init__(self):
        self.connections = []
        self.lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.connections.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.connections:
                self.connections.remove(q)

    def broadcast(self, event_type, data):
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with self.lock:
            for q in self.connections[:]:
                try:
                    q.put_nowait(message)
                except queue.Full:
                    pass


broadcaster = EventBroadcaster()

active_tasks = {}
active_tasks_lock = threading.Lock()


def execute_task(task_id, content, cancel_event):
    broadcaster.broadcast(
        "task_start",
        {
            "task_id": task_id,
            "content": content,
            "message": f"⏰ Executing scheduled task: {content}",
        },
    )

    try:
        if state.tasks_agent is None:
            broadcaster.broadcast(
                "task_error", {"task_id": task_id, "error": "Agent not initialized"}
            )
            return

        result_parts = []
        for chunk in state.tasks_agent.input(content):
            if cancel_event.is_set():
                broadcaster.broadcast("task_cancel", {"task_id": task_id})
                return
            result_parts.append(chunk)
            broadcaster.broadcast("task_chunk", {"task_id": task_id, "chunk": chunk})
        full_result = "".join(result_parts)
        broadcaster.broadcast("task_done", {"task_id": task_id, "result": full_result})
    except Exception as e:
        broadcaster.broadcast("task_error", {"task_id": task_id, "error": str(e)})
    finally:
        with active_tasks_lock:
            if task_id in active_tasks:
                del active_tasks[task_id]


def run_tasks():
    if not hasattr(run_tasks, "_executed"):
        run_tasks._executed = set()
    if not hasattr(run_tasks, "_last_date"):
        run_tasks._last_date = None

    while True:
        if os.path.exists("./tasks.json"):
            try:
                with open("./tasks.json", "r", encoding="utf-8") as f:
                    tasks = json.load(f)
            except Exception as e:
                print(f"[Scheduler] Failed to read tasks.json: {e}", file=sys.stderr)
                pass
            else:
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                today = now.strftime("%Y-%m-%d")

                if today != run_tasks._last_date:
                    run_tasks._executed.clear()
                    run_tasks._last_date = today

                # Support both old Dict format and new List format
                task_list = []
                if isinstance(tasks, dict):
                    # Legacy format: {"HH:MM": "content"}
                    task_list = [{"time": t, "content": c} for t, c in tasks.items()]
                elif isinstance(tasks, list):
                    task_list = tasks

                for task in task_list:
                    time_str = task.get("time", "")
                    content = task.get("content", "")
                    task_key = f"{time_str}:{content}"
                    if time_str == current_time and task_key not in run_tasks._executed:
                        task_id = str(uuid.uuid4())
                        cancel_event = threading.Event()
                        with active_tasks_lock:
                            active_tasks[task_id] = cancel_event
                        thread = threading.Thread(
                            target=execute_task, args=(task_id, content, cancel_event)
                        )
                        thread.daemon = True
                        thread.start()
                        run_tasks._executed.add(task_key)
        time.sleep(10)


# Start scheduler thread
run_tasks_thread = threading.Thread(target=run_tasks, daemon=True)
run_tasks_thread.start()
