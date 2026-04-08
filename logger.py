"""
Logging module for all system actions with CIA Triad considerations.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional


class SystemLogger:
    """Logs all actions with timestamps for audit trail and security."""
    
    def __init__(self, log_file: str = "log.txt"):
        """Initialize logger with specified log file."""
        self.log_file = Path(log_file)
        # Create log file if it doesn't exist
        if not self.log_file.exists():
            self.log_file.touch()
    
    def _format_log_entry(self, action: str, details: str, status: str = "SUCCESS") -> str:
        """Format a log entry with timestamp and details."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return f"[{timestamp}] [{status}] {action}: {details}"
    
    def log_create(self, ticket_id: str, customer_name: str, concert_name: str) -> None:
        """Log ticket creation."""
        entry = self._format_log_entry(
            "CREATE",
            f"Ticket {ticket_id} created for {customer_name} - Concert: {concert_name}"
        )
        self._write_log(entry)
    
    def log_transition(self, ticket_id: str, from_status: str, to_status: str) -> None:
        """Log status transition."""
        entry = self._format_log_entry(
            "TRANSITION",
            f"Ticket {ticket_id}: {from_status} -> {to_status}"
        )
        self._write_log(entry)
    
    def log_transition_failed(self, ticket_id: str, from_status: str, to_status: str, reason: str) -> None:
        """Log failed transition attempt."""
        entry = self._format_log_entry(
            "TRANSITION_FAILED",
            f"Ticket {ticket_id}: {from_status} -> {to_status}. Reason: {reason}",
            "FAILED"
        )
        self._write_log(entry)
    
    def log_modify_attempt_final_stage(self, ticket_id: str) -> None:
        """Log attempt to modify ticket in final stage."""
        entry = self._format_log_entry(
            "MODIFY_BLOCKED",
            f"Ticket {ticket_id}: Modification blocked - ticket in final stage (Issued)",
            "BLOCKED"
        )
        self._write_log(entry)
    
    def log_view(self, ticket_id: str, source: str) -> None:
        """Log ticket view (retrieved from file or cache)."""
        entry = self._format_log_entry(
            "VIEW",
            f"Ticket {ticket_id} retrieved from {source}"
        )
        self._write_log(entry)
    
    def log_search(self, search_type: str, search_value: str, results_count: int) -> None:
        """Log search operation."""
        entry = self._format_log_entry(
            "SEARCH",
            f"Search by {search_type}: '{search_value}' - Found: {results_count} results"
        )
        self._write_log(entry)
    
    def log_delete(self, ticket_id: str) -> None:
        """Log ticket deletion."""
        entry = self._format_log_entry(
            "DELETE",
            f"Ticket {ticket_id} deleted"
        )
        self._write_log(entry)
    
    def log_database_save(self, tickets_count: int) -> None:
        """Log database save operation."""
        entry = self._format_log_entry(
            "DATABASE_SAVE",
            f"Persisted {tickets_count} tickets to database.json"
        )
        self._write_log(entry)
    
    def log_database_load(self, tickets_count: int) -> None:
        """Log database load operation."""
        entry = self._format_log_entry(
            "DATABASE_LOAD",
            f"Loaded {tickets_count} tickets from database.json"
        )
        self._write_log(entry)
    
    def log_cache_hit(self, ticket_id: str) -> None:
        """Log cache hit (for performance monitoring)."""
        entry = self._format_log_entry(
            "CACHE_HIT",
            f"Ticket {ticket_id} served from cache"
        )
        self._write_log(entry)
    
    def log_cache_miss(self, ticket_id: str) -> None:
        """Log cache miss (necessitating file read)."""
        entry = self._format_log_entry(
            "CACHE_MISS",
            f"Ticket {ticket_id} not in cache - loading from file"
        )
        self._write_log(entry)
    
    def log_system_startup(self) -> None:
        """Log system startup."""
        entry = self._format_log_entry(
            "SYSTEM",
            "Concert Ticket Management System started"
        )
        self._write_log(entry)
    
    def log_system_shutdown(self) -> None:
        """Log system shutdown."""
        entry = self._format_log_entry(
            "SYSTEM",
            "Concert Ticket Management System shutdown"
        )
        self._write_log(entry)
    
    def _write_log(self, entry: str) -> None:
        """Write log entry to file."""
        try:
            with open(self.log_file, 'a') as f:
                f.write(entry + "\n")
        except IOError as e:
            print(f"Error writing to log file: {e}")
