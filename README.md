# Concert Ticket Management System - Project Documentation

## Overview
A console-based Python application that implements a resilient concert ticket reservation system with a stateful workflow, caching mechanism, file-based persistence, and comprehensive logging.

## Project Structure

```
pm_project/
├── start.py                 # Main application entry point
├── ticket.py               # Ticket class with state management
├── ticket_system.py        # Core business logic and system controller
├── database.py             # File persistence layer (JSON)
├── cache.py                # In-memory caching mechanism
├── logger.py               # Logging system with audit trail
├── database.json           # Persistent ticket storage
├── log.txt                 # Audit trail and system logs
├── CIA_TRIAD.md            # Security analysis document
└── README.md               # This file
```

## Core Features

### 1. Stateful Workflow (3 pts)
- **Stages**: Reserved → Paid → Issued
- Three distinct states that tickets must progress through in order
- Prevention of illegal transitions (e.g., cannot skip from Reserved to Issued)
- Final stage (Issued) tickets cannot be modified

**Files**: `ticket.py`, `ticket_system.py`

### 2. Simple Caching (3 pts)
- Dictionary-based in-memory cache for performance optimization
- First request retrieves data from database.json file
- Subsequent requests served from cache (logged as CACHE_HIT)
- Cache statistics available showing hit/miss rates

**Files**: `cache.py`, `ticket_system.py`

### 3. File-Based Persistence (3 pts)
- JSON-formatted database.json file as primary storage
- Immediate persistence on every status change
- Each ticket contains timestamp history for every stage transition
- Crash recovery: all data survives program termination

**Files**: `database.py`, `ticket.py`

### 4. Logging & Security (3 pts)
- Comprehensive audit logging in log.txt with timestamps
- Every action recorded (CREATE, TRANSITION, SEARCH, etc.)
- Success/failure status tracked for each operation
- CIA Triad implementation documented in CIA_TRIAD.md

**Files**: `logger.py`, `CIA_TRIAD.md`

### 5. Enhanced Features (3 pts)
- **Console Menu**: User-friendly interface for all operations
- **Search Functionality**: 
  - By Ticket ID (exact match)
  - By Status (Reserved/Paid/Issued)
  - By Customer Name (partial match)
  - By Concert Name (partial match)
- **Timestamps**: Recorded for each stage transition
- **Validation**: Prevents illegal transitions and modifications to final stage

**Files**: `start.py`, `ticket_system.py`

## How to Run

### Prerequisites
- Python 3.8 or higher
- No external dependencies required (uses only standard library)

### Execution
```bash
python start.py
```

The application starts with a welcome screen and interactive menu.

## User Guide

### Main Menu Options

1. **Create New Ticket**
   - Enter Ticket ID, Customer Name, Concert Name, and Price
   - New tickets start in "Reserved" status
   - Automatically logged and persisted

2. **View Ticket Details**
   - Enter Ticket ID to view full details
   - Shows current status and all timestamps
   - Demonstrates cache functionality on repeated views

3. **Update Ticket Status**
   - Transition ticket to next valid stage
   - Validates state transitions
   - Logs the transition with timestamp

4. **Search Tickets**
   - Multiple search options: ID, Status, Customer, Concert
   - Results displayed in formatted table
   - All searches are logged

5. **View All Tickets**
   - Shows all tickets in table format
   - Sorted by Ticket ID

6. **Delete Ticket**
   - Requires confirmation
   - Removes from both cache and database
   - Logged for audit trail

7. **View System Statistics**
   - Cache hit/miss statistics
   - Ticket count by status
   - Performance metrics

8. **View Recent Logs**
   - Shows last 30 log entries
   - Useful for auditing operations

## Test Procedures (In-Class Defense)

### Cache Test
```
1. Open application
2. Select "View Ticket Details"
3. Enter Ticket ID "TICKET001"
   → First access reads from FILE (log shows CACHE_MISS, VIEW from FILE)
4. Select "View Ticket Details" again
5. Enter same Ticket ID "TICKET001"
   → Second access reads from CACHE (log shows CACHE_HIT, VIEW from CACHE)
```

### Crash Test
```
1. Create Ticket: Create → Paid (in Stage 2)
   ID: "CRASH_TEST", Customer: "John", Concert: "Event", Price: $100
   → Check log.txt shows TRANSITION from Reserved to Paid
2. Check database.json - ticket shows status: "Paid" with timestamp
3. Force quit: Close terminal or press Ctrl+C
4. Restart: python start.py
5. Select "View Ticket Details" and enter "CRASH_TEST"
   → Ticket data is completely restored with status "Paid"
   → Timestamps are intact
   → NO DATA LOSS
```

### Logic Test
```
1. Create Ticket "LOGIC_TEST"
   → Starts in Reserved status
2. Try to transition directly from Reserved → Issued
   → ERROR: "Cannot transition from Reserved to Issued"
   → Log shows TRANSITION_FAILED
3. Transition Reserved → Paid (valid)
   → SUCCESS
4. Transition Paid → Issued (valid)
   → SUCCESS
5. Try to transition Issued → Paid (invalid - final stage)
   → ERROR: "Cannot modify ticket in final stage"
   → Log shows both MODIFY_BLOCKED
```

## File Descriptions

### start.py
Main console application with menu system, user input handling, and display formatting. Entry point for the program.

### ticket.py
Defines the `Ticket` class representing concert tickets. Implements:
- State machine logic
- Valid transition validation
- Timestamp tracking per stage
- JSON serialization/deserialization

### ticket_system.py
Core business logic layer implementing `TicketManagementSystem` class. Orchestrates:
- Cache operations
- Database operations
- Logging
- Business rule validation
- Search and filter operations

### database.py
File persistence layer implementing `TicketDatabase` class. Handles:
- JSON file reading/writing
- Ticket serialization
- Database validation and recovery
- CRUD operations

### cache.py
In-memory caching implementing `TicketCache` class. Provides:
- Dictionary-based storage
- Hit/miss tracking
- Statistics gathering
- Cache eviction methods

### logger.py
Audit logging implementing `SystemLogger` class. Records:
- All system operations with timestamps
- Success/failure status
- Detailed action information
- CIA Triad compliance

### database.json
JSON file storing all ticket data in format:
```json
{
  "TICKET_ID": {
    "ticket_id": "TICKET_ID",
    "customer_name": "Name",
    "concert_name": "Concert",
    "price": 100.0,
    "status": "Reserved",
    "timestamps": {
      "Reserved": "2026-04-08T10:15:23.456"
    }
  }
}
```

### log.txt
Audit trail with entries like:
```
[2026-04-08 10:15:23.456] [SUCCESS] CREATE: Ticket TICKET_ID created
[2026-04-08 10:16:45.789] [SUCCESS] TRANSITION: Ticket TICKET_ID: Reserved -> Paid
[2026-04-08 10:16:45.790] [SUCCESS] DATABASE_SAVE: Persisted 1 tickets to database.json
```

## Technical Highlights

### State Machine Implementation
```python
VALID_TRANSITIONS = {
    "Reserved": ["Paid"],
    "Paid": ["Issued"],
    "Issued": []  # Final stage
}
```

### Performance Optimization
- Cache hit rate tracking
- First request loads from file, subsequent from memory
- Reduces I/O operations significantly

### Crash Recovery
```python
# On startup: all tickets reloaded from database.json
tickets = database.load_all_tickets()
for ticket in tickets.values():
    cache.put(ticket)
```

### Immutability Protection
```python
def can_be_modified(self) -> bool:
    return not self.is_final_stage()  # Cannot modify if in "Issued"
```

## CIA Triad Implementation Summary

**See CIA_TRIAD.md for detailed analysis**

- **Confidentiality**: Controlled API access, audit logging
- **Integrity**: State validation, final-stage protection, timestamp tracking
- **Availability**: Persistent storage, crash recovery, performance caching

## Grading Checklist

- ✓ Stateful Workflow: Valid transitions enforced, final stage protected
- ✓ Caching: Dictionary-based, hit/miss tracking, performance improvement
- ✓ File Persistence: JSON database, immediate saves, crash recovery
- ✓ Logging & Security: Comprehensive audit trail, CIA Triad explained
- ✓ Enhanced Features: Console menu, search/filter, timestamps, validation
- ✓ All Tests Passable: Cache, Crash, Logic tests documented

## Example Workflow

```
1. python start.py
2. Create Ticket
   - ID: TKT001
   - Customer: Alice
   - Concert: Taylor Swift Eras Tour
   - Price: $150
   → Status: Reserved (logged with timestamp)
   → Saved to database.json and cache

3. View Ticket TKT001
   → First view: Read from FILE (slow)
   → Logged as CACHE_MISS, VIEW from FILE

4. View Ticket TKT001 again
   → Second view: Read from CACHE (fast)
   → Logged as CACHE_HIT, VIEW from CACHE

5. Update Status: Reserved → Paid
   → Validates transition (valid)
   → Updates timestamp
   → Saves to database and cache
   → Logged with old/new status

6. Update Status: Paid → Issued
   → Validates transition (valid)
   → Ticket now in final stage
   → Any future modifications blocked

7. Try Update Status: Issued → Paid
   → ERROR: Cannot modify final stage
   → Logged as MODIFY_BLOCKED

8. Force quit application

9. Restart: python start.py

10. View Ticket TKT001
    → Data fully restored: Paid → Issued transitions intact
    → Timestamps present
    → NO DATA LOSS
```

## Notes for Defense/Demo

- Emphasize immediate persistence (every change saved to database.json)
- Show log.txt to demonstrate comprehensive audit trail
- Cache performance evident when viewing same ticket twice
- State machine prevents logical impossibilities
- Final stage immutability protects transaction integrity
- CIA Triad successfully implemented in all components

---
**Assignment**: INF 395 - Group Lab Project: The "Resilient Service" Prototype
**Topic**: Concert Tickets (Reserved → Paid → Issued)
**Score Target**: 15/15 Points
