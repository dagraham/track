#! /usr/bin/env python3
# NOTE: Tracker and TrackerManager Classes
from prompt_toolkit import prompt
from prompt_toolkit.validation import Validator, ValidationError
import re
from typing import List, Dict, Any, Callable, Mapping
from collections import defaultdict
import json
import os
from datetime import datetime, timedelta
from dateutil.parser import parse, parserinfo
import traceback
import sys

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


class Tracker:
    _next_id = 1
    default_history = [0, "0", None]

    @classmethod
    def format_dt(cls, dt: Any) -> str:
        if not isinstance(dt, datetime):
            return ""
        return dt.strftime("%Y-%m-%d %H:%M")

    @classmethod
    def td2seconds(cls, td: timedelta) -> str:
        if not isinstance(td, timedelta):
            return ""
        return f"{round(td.total_seconds())}"

    @classmethod
    def format_td(cls, td: timedelta):
        if not isinstance(td, timedelta):
            return None
        total_seconds = int(td.total_seconds())
        if total_seconds == 0:
            return ' 0 minutes '
        total_seconds = abs(total_seconds)
        try:
            until = []
            days = hours = minutes = 0
            if total_seconds:
                minutes = total_seconds // 60
                if minutes >= 60:
                    hours = minutes // 60
                    minutes = minutes % 60
                if hours >= 24:
                    days = hours // 24
                    hours = hours % 24
            if days:
                until.append(f'{days} days')
            if hours:
                until.append(f'{hours} hours')
            if minutes:
                until.append(f'{minutes} minutes')
            if not until:
                until.append('0 minuutes')
            ret = ' '.join(until)
            return ret
        except Exception as e:
            print(f'{td}: {e}')
            return ''


    @classmethod
    def parse_dt(cls, dt: str = "") -> datetime:
        if isinstance(dt, datetime):
            return dt
        elif dt.strip() == "now":
            dt = datetime.now()
            return dt
        elif isinstance(dt, str) and dt:
            pi = parserinfo(
                dayfirst=False,
                yearfirst=True)
            try:
                dt = parse(dt, parserinfo=pi)
                return dt
            except Exception as e:
                print(f"Error parsing datetime: {dt}\ne {repr(e)}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
                return None
        else:
            return None

    def __init__(self, name: str, dt: str = "") -> None:
        self.doc_id = Tracker._next_id
        Tracker._next_id += 1
        self.name = name
        self.last_completion = None
        self.last_interval = None
        self.next_expected_completion = None
        self.history = Tracker.default_history

    def record_completion(self, completion_dt: datetime):
        # completion_dt will be a valid datetime
        ok, msg = True, ""
        if self.last_completion and self.last_completion >= completion_dt:
            return False, f"""\
    Entry error: The new completion datetime
        {completion_dt}
    must be later than the previous completion datetime
        {self.last_completion}."""

        self.last_completion = completion_dt
        num_intervals, average_interval, last_completion = self.history
        if last_completion is None:
            num_intervals = 0
            average_interval = timedelta(minutes=0)
            last_completion = self.last_completion
        else:
            self.last_interval = self.last_completion - last_completion
            total = num_intervals * average_interval + self.last_interval
            num_intervals += 1
            average_interval = total / num_intervals

        self.history = [num_intervals, average_interval, self.last_completion]
        self.next_expected_completion = self.last_completion + average_interval if (self.last_completion is not None and self.history[1] != timedelta(minutes=0)) else None
        return True, f"recorded completion for {self.last_completion}"

    def get_tracker_data(self):
        return f"""{self.name}
       completion intervals: {self.history[0]}
       average interval: {Tracker.format_td(self.history[1])}
       last interval: {Tracker.format_td(self.last_interval)}
       last completion: {Tracker.format_dt(self.last_completion)}
       next expected completion: {Tracker.format_dt(self.next_expected_completion)}"""

    # def get_tracker_data(self):
    #     return f"""{self.name}
    #    average interval {str(self.history[1])} based on {self.history[0]} intervals
    #    last completed {Tracker.format_dt(self.last_completion)} after {str(self.last_interval)}
    #    next completion expected at {Tracker.format_dt(self.next_expected_completion)}"""

class TrackerManager:
    def __init__(self, file_path=None) -> None:
        if file_path is None:
            file_path = os.path.join(os.getcwd(), "tracker.json")
        self.file_path = file_path
        self.trackers = {}
        self.load_data(self.file_path)

    def add_tracker(self, tracker) -> None:
        doc_id = tracker.doc_id
        self.trackers[doc_id] = tracker
        self.save_data(self.file_path)

    def record_completion(self, doc_id: int, dt: datetime):
        # dt will be a datetime
        ok, msg = self.trackers[doc_id].record_completion(dt)
        if not ok:
            print(msg)
            return

        self.save_data(self.file_path)
        print(f"""\
                {doc_id}: Recorded {dt.strftime('%Y-%m-%d %H:%M')} as a completion:\n    {self.trackers[doc_id].get_tracker_data()}""")

    def get_tracker_data(self, doc_id: int = None):

        if doc_id is None:
            print("data for all trackers:")
            for k, v in self.trackers.items():
                print(f"   {k:2> }. {v.get_tracker_data()}")
        elif doc_id in self.trackers:
            print(f"data for tracker {doc_id}:")
            print(f"   {doc_id:2> }. {self.trackers[doc_id].get_tracker_data()}")

    def list_trackers(self):
        print(f"all trackers:")
        for k, v in self.trackers.items():
            print(f"   {k:2> }. {v.name}")

    def save_data(self, file_path):
        data = {doc_id: {
                    'name': tracker.name,
                    'last_completion': Tracker.format_dt(tracker.last_completion),
                    'last_interval': Tracker.td2seconds(tracker.last_interval),
                    'next_expected_completion': Tracker.format_dt(tracker.next_expected_completion),
                    'history': [tracker.history[0], Tracker.td2seconds(tracker.history[1]), Tracker.format_dt(tracker.history[2])]
                } for doc_id, tracker in self.trackers.items()}
        with open(file_path, 'w') as file:
            json.dump(data, file, indent=2)

    def load_data(self, file_path):
        try:
            with open(file_path, 'r') as file:
                data = json.load(file)
                for doc_id, tracker_data in data.items():
                    tracker = Tracker(tracker_data['name'])
                    tracker.doc_id = int(doc_id)
                    Tracker._next_id = max(Tracker._next_id, tracker.doc_id + 1)
                    tracker.last_completion = Tracker.parse_dt(tracker_data['last_completion'])
                    tracker.last_interval = self.parse_timedelta(tracker_data['last_interval'])
                    tracker.next_expected_completion = Tracker.parse_dt(tracker_data['next_expected_completion'])
                    tracker.history = [
                        tracker_data['history'][0],
                        self.parse_timedelta(tracker_data['history'][1]),
                        Tracker.parse_dt(tracker_data['history'][2])
                    ]
                    self.trackers[tracker.doc_id] = tracker
        except FileNotFoundError:
            self.trackers = {}

    @staticmethod
    def parse_timedelta(td_str):
        if not td_str:
            return None
        else:
            total_seconds = int(td_str)
            return timedelta(seconds=total_seconds)

    def update_tracker(self, doc_id, tracker):
        self.trackers[doc_id] = tracker
        self.save_data(self.file_path)

    def delete_tracker(self, doc_id):
        if doc_id in self.trackers:
            del self.trackers[doc_id]
            self.save_data(self.file_path)

    def get_tracker(self, doc_id):
        return self.trackers.get(doc_id, None)

def main():
    file_path = os.path.join(os.getcwd(), "tracker.json")
    if not os.path.exists(file_path):
        print(f"Warning: '{file_path}' does not exist and will be created.")
        ok = input("Continue? (y/n) ").strip().lower() == 'y'
        if not ok:
            sys.exit("Aborted.")
    tracker_manager = TrackerManager(file_path)
    tracker_manager.list_trackers()
    last_id = None
    clear_screen()

    while True:
        print("Menu:")
        print("    a) add tracker")
        print("    d) delete tracker")
        print("    l) list trackers")
        print("    r) record completion")
        print("    s) show tracker info")
        print("    c) clear screen")
        print("    q) quit")

        choice = input("Choose an option: ").strip().lower()

        if choice == 'a':
            name = input("Enter tracker name: ").strip()
            new_tracker = Tracker(name)
            tracker_manager.add_tracker(new_tracker)
            last_id = new_tracker.doc_id
            print(f"Tracker '{name}' added with ID {new_tracker.doc_id}")

        elif choice == 'd':
            try:
                doc_id_input = input(f"Enter tracker ID to delete [{last_id}]: ").strip()
                doc_id = int(doc_id_input) if doc_id_input else last_id
                if doc_id is not None:
                    tracker_manager.delete_tracker(doc_id)
                    print(f"Tracker with ID {doc_id} deleted")
                else:
                    print("No ID provided.")
            except ValueError:
                print("Invalid ID. Please enter a numeric value.")

        elif choice == 'l':
            tracker_manager.list_trackers()

        elif choice == 'r':
            tracker_manager.list_trackers()
            try:
                doc_id_input = input(f"Enter tracker ID [{last_id}]: ").strip()
                doc_id = int(doc_id_input) if doc_id_input else last_id
                if doc_id is not None:
                    last_id = doc_id
                    dt_str = input(f"Enter completion datetime for {doc_id}: ").strip()
                    dt = Tracker.parse_dt(dt_str)
                    if dt:
                        tracker_manager.record_completion(doc_id, dt)
                    else:
                        print("Invalid datetime format. Please try again.")
                else:
                    print("No ID provided.")
            except ValueError:
                print("Invalid ID. Please enter a numeric value.")

        elif choice == 's':
            try:
                doc_id_input = input(f"Enter tracker ID (or 0 for all) [{last_id}]: ").strip()
                doc_id = int(doc_id_input) if doc_id_input else last_id
                if doc_id is not None:
                    if doc_id == 0:
                        tracker_manager.get_tracker_data()
                    else:
                        last_id = doc_id
                        tracker_manager.get_tracker_data(doc_id)
                else:
                    print("No ID provided.")
            except ValueError:
                print("Invalid ID. Please enter a numeric value.")

        elif choice == 'c':
            clear_screen()

        elif choice == 'q':
            print("Quitting...")
            sys.exit()

        else:
            print("Invalid option. Please choose again.")

if __name__ == "__main__":
    main()

