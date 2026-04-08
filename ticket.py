"""
Ticket class with stateful workflow management.
Stages: Reserved -> Paid -> Issued
"""
from datetime import datetime
from typing import Dict, Any


class Ticket:
    """Concert ticket with stateful workflow and timestamp tracking."""
    
    # Valid stage transitions
    VALID_TRANSITIONS = {
        "Reserved": ["Paid"],
        "Paid": ["Issued"],
        "Issued": []  # Final stage - no transitions
    }
    
    STAGES = ["Reserved", "Paid", "Issued"]
    
    def __init__(self, ticket_id: str, customer_name: str, concert_name: str, price: float):
        """Initialize a new ticket in Reserved stage."""
        self.ticket_id = ticket_id
        self.customer_name = customer_name
        self.concert_name = concert_name
        self.price = price
        self.status = "Reserved"
        
        # Timestamp tracking for each stage
        self.timestamps: Dict[str, str] = {
            "Reserved": datetime.now().isoformat()
        }
    
    def can_transition(self, new_status: str) -> bool:
        """Check if transition from current status to new_status is valid."""
        return new_status in self.VALID_TRANSITIONS.get(self.status, [])
    
    def transition_to(self, new_status: str) -> bool:
        """
        Attempt to transition to a new status.
        Returns True if successful, False otherwise.
        """
        if not self.can_transition(new_status):
            return False
        
        self.status = new_status
        self.timestamps[new_status] = datetime.now().isoformat()
        return True
    
    def is_final_stage(self) -> bool:
        """Check if ticket is in final stage (Issued)."""
        return self.status == "Issued"
    
    def can_be_modified(self) -> bool:
        """Check if ticket can be modified (not in final stage)."""
        return not self.is_final_stage()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ticket to dictionary for JSON serialization."""
        return {
            "ticket_id": self.ticket_id,
            "customer_name": self.customer_name,
            "concert_name": self.concert_name,
            "price": self.price,
            "status": self.status,
            "timestamps": self.timestamps
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Ticket':
        """Create a Ticket instance from a dictionary."""
        ticket = cls(
            data["ticket_id"],
            data["customer_name"],
            data["concert_name"],
            data["price"]
        )
        ticket.status = data["status"]
        ticket.timestamps = data["timestamps"]
        return ticket
    
    def __repr__(self) -> str:
        """String representation of the ticket."""
        return (f"Ticket(id={self.ticket_id}, customer={self.customer_name}, "
                f"concert={self.concert_name}, status={self.status}, price={self.price})")
