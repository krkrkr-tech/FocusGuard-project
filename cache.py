"""
Simple caching mechanism for ticket management.
Stores frequently accessed tickets in memory for performance improvement.
"""
from typing import Dict, Optional
from ticket import Ticket


class TicketCache:
    """Dictionary-based cache for ticket objects."""
    
    def __init__(self):
        """Initialize empty cache."""
        self._cache: Dict[str, Ticket] = {}
        self._hit_count = 0
        self._miss_count = 0
    
    def get(self, ticket_id: str) -> Optional[Ticket]:
        """
        Retrieve a ticket from cache if it exists.
        Returns None if not found.
        """
        if ticket_id in self._cache:
            self._hit_count += 1
            return self._cache[ticket_id]
        self._miss_count += 1
        return None
    
    def put(self, ticket: Ticket) -> None:
        """Store a ticket in cache."""
        self._cache[ticket.ticket_id] = ticket
    
    def update(self, ticket: Ticket) -> None:
        """Update an existing ticket in cache."""
        if ticket.ticket_id in self._cache:
            self._cache[ticket.ticket_id] = ticket
    
    def remove(self, ticket_id: str) -> bool:
        """
        Remove a ticket from cache.
        Returns True if removed, False if not found.
        """
        if ticket_id in self._cache:
            del self._cache[ticket_id]
            return True
        return False
    
    def clear(self) -> None:
        """Clear all cached tickets."""
        self._cache.clear()
    
    def exists(self, ticket_id: str) -> bool:
        """Check if a ticket exists in cache."""
        return ticket_id in self._cache
    
    def get_all(self) -> Dict[str, Ticket]:
        """Get all cached tickets as a dictionary."""
        return self._cache.copy()
    
    def size(self) -> int:
        """Get number of tickets in cache."""
        return len(self._cache)
    
    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        total_requests = self._hit_count + self._miss_count
        hit_rate = (self._hit_count / total_requests * 100) if total_requests > 0 else 0
        return {
            "hits": self._hit_count,
            "misses": self._miss_count,
            "total_requests": total_requests,
            "hit_rate_percent": round(hit_rate, 2),
            "cached_items": len(self._cache)
        }
    
    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._hit_count = 0
        self._miss_count = 0
