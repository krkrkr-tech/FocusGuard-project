"""
File-based persistence layer for ticket database.
Uses JSON format for data storage and recovery.
"""
import json
from pathlib import Path
from typing import Dict, List, Any
from ticket import Ticket
from logger import SystemLogger


class TicketDatabase:
    """Handles file-based persistence with JSON format."""
    
    def __init__(self, db_file: str = "database.json", logger: SystemLogger = None):
        """Initialize database with specified file."""
        self.db_file = Path(db_file)
        self.logger = logger or SystemLogger()
        self._ensure_db_exists()
    
    def _ensure_db_exists(self) -> None:
        """Ensure database file exists and is valid JSON."""
        if self.db_file.exists():
            try:
                with open(self.db_file, 'r') as f:
                    json.load(f)
            except (json.JSONDecodeError, IOError):
                # If file is corrupted, reinitialize
                self._write_db({})
        else:
            self._write_db({})
    
    def _read_db(self) -> Dict[str, Any]:
        """Read all data from database file."""
        try:
            with open(self.db_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    
    def _write_db(self, data: Dict[str, Any]) -> None:
        """Write data to database file."""
        try:
            with open(self.db_file, 'w') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Error writing to database: {e}")
    
    def save_ticket(self, ticket: Ticket) -> bool:
        """
        Save or update a ticket in the database.
        Returns True if successful.
        """
        try:
            data = self._read_db()
            data[ticket.ticket_id] = ticket.to_dict()
            self._write_db(data)
            self.logger.log_database_save(len(data))
            return True
        except Exception as e:
            print(f"Error saving ticket: {e}")
            return False
    
    def save_all_tickets(self, tickets: Dict[str, Ticket]) -> bool:
        """
        Save multiple tickets to the database.
        Returns True if successful.
        """
        try:
            data = {tid: ticket.to_dict() for tid, ticket in tickets.items()}
            self._write_db(data)
            self.logger.log_database_save(len(data))
            return True
        except Exception as e:
            print(f"Error saving tickets: {e}")
            return False
    
    def load_ticket(self, ticket_id: str) -> Ticket | None:
        """
        Load a single ticket from the database.
        Returns None if not found.
        """
        try:
            data = self._read_db()
            if ticket_id in data:
                return Ticket.from_dict(data[ticket_id])
            return None
        except Exception as e:
            print(f"Error loading ticket: {e}")
            return None
    
    def load_all_tickets(self) -> Dict[str, Ticket]:
        """
        Load all tickets from the database.
        Returns a dictionary of ticket_id -> Ticket.
        """
        try:
            data = self._read_db()
            tickets = {}
            for ticket_id, ticket_data in data.items():
                tickets[ticket_id] = Ticket.from_dict(ticket_data)
            self.logger.log_database_load(len(tickets))
            return tickets
        except Exception as e:
            print(f"Error loading tickets: {e}")
            return {}
    
    def delete_ticket(self, ticket_id: str) -> bool:
        """
        Delete a ticket from the database.
        Returns True if successful, False if not found.
        """
        try:
            data = self._read_db()
            if ticket_id in data:
                del data[ticket_id]
                self._write_db(data)
                self.logger.log_delete(ticket_id)
                return True
            return False
        except Exception as e:
            print(f"Error deleting ticket: {e}")
            return False
    
    def get_all_ids(self) -> List[str]:
        """Get list of all ticket IDs in database."""
        try:
            data = self._read_db()
            return list(data.keys())
        except Exception as e:
            print(f"Error getting ticket IDs: {e}")
            return []
    
    def ticket_exists(self, ticket_id: str) -> bool:
        """Check if a ticket exists in the database."""
        try:
            data = self._read_db()
            return ticket_id in data
        except Exception as e:
            print(f"Error checking ticket existence: {e}")
            return False
    
    def count_tickets(self) -> int:
        """Get total number of tickets in database."""
        try:
            data = self._read_db()
            return len(data)
        except Exception as e:
            print(f"Error counting tickets: {e}")
            return 0
