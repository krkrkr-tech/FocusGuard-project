"""
Main Ticket Management System that integrates all components.
Handles business logic, caching, persistence, and logging.
"""
from typing import Dict, List, Optional, Tuple
from ticket import Ticket
from cache import TicketCache
from database import TicketDatabase
from logger import SystemLogger


class TicketManagementSystem:
    """Core system managing concert tickets with stateful workflow."""
    
    def __init__(self):
        """Initialize the system with cache, database, and logger."""
        self.logger = SystemLogger()
        self.database = TicketDatabase(logger=self.logger)
        self.cache = TicketCache()
        self.logger.log_system_startup()
        self._load_initial_cache()
    
    def _load_initial_cache(self) -> None:
        """Load all tickets from database into cache on startup."""
        tickets = self.database.load_all_tickets()
        for ticket in tickets.values():
            self.cache.put(ticket)
    
    def create_ticket(self, ticket_id: str, customer_name: str, concert_name: str, price: float) -> Tuple[bool, str]:
        """
        Create a new ticket.
        Returns (success, message)
        """
        # Validate inputs
        if not ticket_id or not customer_name or not concert_name or price <= 0:
            return False, "Invalid input: all fields required and price must be positive"
        
        # Check if ticket already exists
        if self.cache.exists(ticket_id) or self.database.ticket_exists(ticket_id):
            return False, f"Ticket {ticket_id} already exists"
        
        try:
            # Create new ticket
            ticket = Ticket(ticket_id, customer_name, concert_name, price)
            
            # Save to database and cache
            self.database.save_ticket(ticket)
            self.cache.put(ticket)
            self.logger.log_create(ticket_id, customer_name, concert_name)
            
            return True, f"Ticket {ticket_id} created successfully - Status: {ticket.status}"
        except Exception as e:
            return False, f"Error creating ticket: {str(e)}"
    
    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        """
        Get a ticket by ID (from cache or database).
        Demonstrates cache functionality: first request loads from file, second from cache.
        """
        # Check cache first (performance optimization)
        cached_ticket = self.cache.get(ticket_id)
        if cached_ticket:
            self.logger.log_cache_hit(ticket_id)
            self.logger.log_view(ticket_id, "CACHE")
            return cached_ticket
        
        # Cache miss - load from database
        self.logger.log_cache_miss(ticket_id)
        ticket = self.database.load_ticket(ticket_id)
        
        if ticket:
            self.cache.put(ticket)
            self.logger.log_view(ticket_id, "FILE")
            return ticket
        
        return None
    
    def transition_ticket(self, ticket_id: str, new_status: str) -> Tuple[bool, str]:
        """
        Transition a ticket to a new status.
        Validates the transition legality.
        Returns (success, message)
        """
        ticket = self.get_ticket(ticket_id)
        
        if not ticket:
            return False, f"Ticket {ticket_id} not found"
        
        # Check if modification is allowed (final stage protection)
        if not ticket.can_be_modified():
            self.logger.log_modify_attempt_final_stage(ticket_id)
            return False, f"Cannot modify ticket {ticket_id}: already in final stage (Issued)"
        
        # Validate new status
        if new_status not in Ticket.STAGES:
            return False, f"Invalid status: {new_status}. Valid statuses: {', '.join(Ticket.STAGES)}"
        
        # Check if transition is valid
        if not ticket.can_transition(new_status):
            old_status = ticket.status
            valid_next = Ticket.VALID_TRANSITIONS.get(old_status, [])
            self.logger.log_transition_failed(ticket_id, old_status, new_status, "Invalid stage transition")
            return False, f"Cannot transition from {old_status} to {new_status}. Valid next stages: {', '.join(valid_next)}"
        
        # Perform transition
        old_status = ticket.status
        ticket.transition_to(new_status)
        
        # Update cache and database
        self.cache.update(ticket)
        self.database.save_ticket(ticket)
        self.logger.log_transition(ticket_id, old_status, new_status)
        
        return True, f"Ticket {ticket_id} transitioned: {old_status} → {new_status}"
    
    def search_by_id(self, ticket_id: str) -> Optional[Ticket]:
        """Search for a ticket by exact ID match."""
        ticket = self.get_ticket(ticket_id)
        self.logger.log_search("ID", ticket_id, 1 if ticket else 0)
        return ticket
    
    def search_by_status(self, status: str) -> List[Ticket]:
        """Search for all tickets with a specific status."""
        if status not in Ticket.STAGES:
            self.logger.log_search("STATUS", status, 0)
            return []
        
        all_tickets = self.cache.get_all()
        matching = [t for t in all_tickets.values() if t.status == status]
        self.logger.log_search("STATUS", status, len(matching))
        return matching
    
    def search_by_customer(self, customer_name: str) -> List[Ticket]:
        """Search for all tickets by customer name (partial match)."""
        all_tickets = self.cache.get_all()
        matching = [t for t in all_tickets.values() 
                   if customer_name.lower() in t.customer_name.lower()]
        self.logger.log_search("CUSTOMER", customer_name, len(matching))
        return matching
    
    def search_by_concert(self, concert_name: str) -> List[Ticket]:
        """Search for all tickets by concert name (partial match)."""
        all_tickets = self.cache.get_all()
        matching = [t for t in all_tickets.values() 
                   if concert_name.lower() in t.concert_name.lower()]
        self.logger.log_search("CONCERT", concert_name, len(matching))
        return matching
    
    def get_all_tickets(self) -> List[Ticket]:
        """Get all tickets sorted by ticket ID."""
        return sorted(self.cache.get_all().values(), key=lambda t: t.ticket_id)
    
    def delete_ticket(self, ticket_id: str) -> Tuple[bool, str]:
        """Delete a ticket from system."""
        if not self.cache.exists(ticket_id) and not self.database.ticket_exists(ticket_id):
            return False, f"Ticket {ticket_id} not found"
        
        self.cache.remove(ticket_id)
        success = self.database.delete_ticket(ticket_id)
        
        if success:
            return True, f"Ticket {ticket_id} deleted successfully"
        else:
            return False, f"Error deleting ticket {ticket_id}"
    
    def get_cache_stats(self) -> Dict:
        """Get cache performance statistics."""
        return self.cache.get_stats()
    
    def shutdown(self) -> None:
        """Graceful system shutdown."""
        self.logger.log_system_shutdown()
