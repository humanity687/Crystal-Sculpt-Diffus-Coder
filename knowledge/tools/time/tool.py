# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Get Time Tool
Returns the current local date and time
"""

from datetime import datetime

schema = {
    "type": "function",
    "function": {
        "name": "time",
        "description": "Get the current local date and time. No parameters needed.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def execute() -> str:
    """
    Get current date and time

    Returns:
        Formatted datetime string, e.g., "2024-01-15 Wednesday 15:30:45"
    """
    now = datetime.now()

    # List of weekday names
    weekdays = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    # Get the day of the week (0=Monday, 6=Sunday)
    weekday = weekdays[now.weekday()]

    # Return formatted string
    return now.strftime(f"%Y-%m-%d {weekday} %H:%M:%S")
