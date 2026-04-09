# Concert Ticket Management System - Architecture Overview

## High-Level Architecture

```
┌─────────────────────────────────────────────┐
│         Console User Interface              │
│              (start.py)                     │
│  - Menu system                              │
│  - Input validation                         │
│  - Formatted output display                 │
└────────────────┬────────────────────────────┘
                 │
┌─────────────────▼────────────────────────────┐
│    Ticket Management System (Core Logic)     │
│         (ticket_system.py)                  │
│  - Business rules                           │
│  - State validation                         │
│  - Orchestrates cache & database            │
└────────────────┬────────────────────────────┘
        ┌───────┴───────┬───────────┬────────┐
        │               │           │        │
   ┌────▼──┐  ┌────────▼──┐  ┌────▼──┐  ┌─▼─────┐
   │Ticket │  │  System   │  │  File │  │Cache │
   │Model  │  │  Logger   │  │       │  │      │
   │       │  │           │  │  DB   │  │      │
   │States │  │ Audit Log │  │       │  │      │
   └───────┘  └───────────┘  └───────┘  └──────┘
   (ticket.py) (logger.py)  (database.py)(cache.py)
                    │            │
                    │            └────────► database.json (JSON File)
                    │
                    └────────────────────► log.txt (Audit Log)
```
## Component Responsibilities

### 1. **Ticket Model (ticket.py)**
**Responsibility**: Define ticket structure and state machine logic

**Key Features**:
- Three-state workflow: Reserved → Paid → Issued
- Validate state transitions
- Prevent modifications in final stage
- Track timestamps for each stage

**Key Methods**:
- `can_transition(new_status)`: Validate if transition is allowed
- `transition_to(new_status)`: Perform state transition
- `is_final_stage()`: Check if ticket is in Issued stage
- `to_dict() / from_dict()`: JSON serialization

### 2. **System Logger (logger.py)**
**Responsibility**: Record all actions for audit trail

**Key Features**:
- Comprehensive action logging
- Timestamp precision (milliseconds)
- Success/failure status tracking
- Supports CIA Triad compliance

**Key Methods**:
- `log_create()`: Log ticket creation
- `log_transition()`: Log state changes
- `log_cache_hit/miss()`: Log cache operations
- `log_transition_failed()`: Log blocked transitions

### 3. **File Database (database.py)**
**Responsibility**: Handle persistent storage with immediate updates

**Key Features**:
- JSON format for human readability
- Automatic recovery of corrupted files
- Immediate persistence of all changes
- Single source of truth for data

**Key Methods**:
- `save_ticket()`: Save/update ticket
- `load_ticket()`: Load by ID
- `load_all_tickets()`: Load all for cache population
- `delete_ticket()`: Remove ticket

### 4. **In-Memory Cache (cache.py)**
**Responsibility**: Optimize performance with frequently accessed data

**Key Features**:
- Dictionary-based storage
- Hit/miss statistics
- Simple put/get operations
- No persistence (cleared on shutdown)

**Key Methods**:
- `get()`: Retrieve from cache (with statistics)
- `put()`: Store in cache
- `exists()`: Check cache membership
- `get_stats()`: Performance metrics

### 5. **Ticket Management System (ticket_system.py)**
**Responsibility**: Orchestrate all components with business logic

**Key Features**:
- Initialize logger, database, cache
- Populate cache on startup
- Route all operations through validation
- Enforce business rules

**Key Methods**:
- `create_ticket()`: Create new ticket
- `get_ticket()`: Retrieve by demonstrating cache logic
- `transition_ticket()`: Update status with validation
- `search_*()`: Various search methods

### 6. **Console Application (start.py)**
**Responsibility**: User interface and menu system

**Key Features**:
- User-friendly menu
- Input validation
- Formatted output
- Error handling

---

## Data Flow Examples

### Example 1: Creating a Ticket (Initialization Flow)
```
User Input (Create Menu)
         ↓
    Validate Input
         ↓
    Create Ticket Object (ticket.py)
         ↓
    Get from Database (new ticket)
         ↓
    Add to Cache
         ↓
    Log to log.txt (logger.py)
         ↓
    Save to database.json (database.py)
         ↓
    Display Success Message
```

### Example 2: Viewing a Ticket (Cache Priority Flow)
```
User Input (View Menu)
         ↓
    Check Cache (cache.py)
         ├─ HIT ──────► Log Cache Hit ──► Return Ticket
         │
         └─ MISS ──► Load from database.json (database.py)
                              ↓
                          Add to Cache
                              ↓
                          Log Cache Miss
                              ↓
                          Return Ticket
```

### Example 3: Updating Status (Validation + Persistence Flow)
```
User Input (New Status)
         ↓
    Get Ticket from Cache/DB
         ↓
    Check if in Final Stage?
    ├─ YES ──► ERROR: Cannot modify ──► Log Blocked
    │
    └─ NO ──► Validate Transition?
               ├─ INVALID ──► ERROR: Illegal transition ──► Log Failed
               │
               └─ VALID ──► Update Status + Timestamp
                              ↓
                         Update Cache
                              ↓
                    Save to database.json
                              ↓
                         Log Transition
                              ↓
                    Display Success Message
```

### Example 4: System Startup (Recovery Flow)
```
Application Start
         ↓
    Initialize Logger
         ↓
    Initialize Database
         ├─ Load database.json
         └─ Validate JSON format
         ↓
    Initialize Cache (empty)
         ↓
    Load All Tickets from Database
         ↓
    Populate Cache with All Tickets
         ↓
    Log System Startup
         ↓
    Display Main Menu
```

### Example 5: System Crash & Recovery (Resilience Flow)
```
Before Crash: Ticket TICKET_001
    Status: Reserved ──► Paid
    database.json: Updated Immediately ✓
    cache: Updated ✓
    log.txt: Logged ✓

System Crash/Forced Quit

After Restart:
    database.json: Still contains status Paid ✓
    Application loads database.json during startup
    Cache repopulated from database.json
    Ticket TICKET_001 restored with status Paid ✓
    NO DATA LOSS
```

---

## State Transition Diagram

```
                    ┌────────────────┐
                    │   RESERVED     │
                    │   (Initial)    │
                    └────────┬───────┘
                             │
                    [Transition: Paid]
                             │
                             ▼
                    ┌────────────────┐
                    │      PAID      │
                    │  (Intermediate)│
                    └────────┬───────┘
                             │
                   [Transition: Issued]
                             │
                             ▼
                    ┌────────────────┐
                    │     ISSUED     │
                    │ (Final - RO)   │
                    └────────────────┘
                    
Legend:
- Blocking: Reserved ≠X→ Issued (skip not allowed)
- Blocking: Issued ≠X→ Any (immutable final stage)
- RO = Read-Only (cannot be modified)
```

---

## Storage & Persistence Strategy

### JSON Database Format
```json
{
  "TICKET_001": {
    "ticket_id": "TICKET_001",
    "customer_name": "John Doe",
    "concert_name": "The Weeknd",
    "price": 200.0,
    "status": "Paid",
    "timestamps": {
      "Reserved": "2026-04-08T10:15:23.456",
      "Paid": "2026-04-08T10:16:45.789"
    }
  },
  "TICKET_002": {
    // ... similar structure
  }
}
```

**Benefits**:
- Human-readable format
- Easy to inspect/debug
- Valid JSON ensures data integrity
- Timestamps track all changes
- Survives program termination

---

## Caching Strategy

### First Access (Cache Miss)
```
Request for Ticket T001
         ↓
Check Cache
    ├─ NOT FOUND ←─── CACHE MISS
         ↓
Load from database.json (file I/O - slower)
         ↓
Store in Cache (in-memory)
         ↓
Return to User
         ↓
Log: CACHE_MISS, VIEW from FILE
```

### Subsequent Access (Cache Hit)
```
Request for Ticket T001 (second time)
         ↓
Check Cache
    ├─ FOUND ←─── CACHE HIT
         ↓
Return from Cache (memory only - faster)
         ↓
Log: CACHE_HIT, VIEW from CACHE
```

**Performance Impact**:
- First request: ~1-5ms (file I/O)
- Subsequent requests: <1ms (memory access)
- 50-99% hit rate in typical usage
- Reduces disk load significantly

---

## Logging Strategy

### Log Entry Format
```
[YYYY-MM-DD HH:MM:SS.mmm] [STATUS] ACTION: Details
```

### Example Logs

#### Success
```
[2026-04-08 10:15:23.456] [SUCCESS] CREATE: Ticket TICKET_001 created
[2026-04-08 10:16:45.789] [SUCCESS] TRANSITION: Ticket TICKET_001: Reserved -> Paid
[2026-04-08 10:16:45.790] [SUCCESS] DATABASE_SAVE: Persisted 1 tickets to database.json
```

#### Failures/Blocks
```
[2026-04-08 10:17:00.123] [FAILED] TRANSITION_FAILED: Ticket TICKET_001: Reserved -> Issued
[2026-04-08 10:17:15.456] [BLOCKED] MODIFY_BLOCKED: Ticket TICKET_001: already in final stage
```

#### Cache Operations
```
[2026-04-08 10:18:00.789] [SUCCESS] CACHE_MISS: Ticket TICKET_001 not in cache
[2026-04-08 10:18:01.012] [SUCCESS] CACHE_HIT: Ticket TICKET_001 served from cache
```

**Audit Trail Benefits**:
- Forensic analysis possible
- Tracks exactly when changes occurred
- Provides evidence of system health
- Enables compliance verification

---

## Security Features (CIA Triad)

### Confidentiality
- Cache is in-memory only (not persisted)
- Access controlled through API
- Search results filtered by query
- Audit logged for accountability

### Integrity
- State machine validates all transitions
- Final stage (Issued) is immutable
- Timestamps create change history
- JSON format ensures well-formed data

### Availability
- Crash recovery via database.json
- Performance caching reduces latency
- Error handling prevents cascading failures
- Comprehensive logging for diagnostics

---

## Design Patterns Used

### 1. **State Pattern**
- Ticket has explicit states: Reserved, Paid, Issued
- State transitions controlled by state machine
- Prevents invalid state sequences

### 2. **Cache Pattern (with Performance Optimization)**
- Dictionary-based in-memory cache
- First request loads from source (database)
- Subsequent requests served from cache
- Hit/miss statistics for optimization

### 3. **Repository Pattern**
- TicketDatabase abstracts file storage
- CRUD operations through defined interface
- Persistence details hidden from business logic

### 4. **Facade Pattern**
- TicketManagementSystem orchestrates all components
- Simple public interface for complex operations
- Internal complexity hidden from UI layer

### 5. **Strategy Pattern**
- Multiple search strategies: ID, Status, Customer, Concert
- Each search optimized for its purpose
- Extensible for new search types

---

## Class Diagram

```
┌──────────────────────────┐
│        Ticket            │
├──────────────────────────┤
│ - ticket_id              │
│ - customer_name          │
│ - concert_name           │
│ - price                  │
│ - status                 │
│ - timestamps             │
├──────────────────────────┤
│ + can_transition()       │
│ + transition_to()        │
│ + is_final_stage()       │
│ + to_dict()              │
│ + from_dict()            │
└──────────────────────────┘

┌──────────────────────────┐
│   TicketManagementSystem │
├──────────────────────────┤
│ - cache: TicketCache     │
│ - database: TicketDB     │
│ - logger: SystemLogger   │
├──────────────────────────┤
│ + create_ticket()        │
│ + get_ticket()           │
│ + transition_ticket()    │
│ + search_by_*()          │
│ + delete_ticket()        │
└──────────────────────────┘

┌──────────────────────────┐
│   TicketDatabase         │
├──────────────────────────┤
│ - db_file: Path          │
│ - logger: SystemLogger   │
├──────────────────────────┤
│ + save_ticket()          │
│ + load_ticket()          │
│ + delete_ticket()        │
│ + ticket_exists()        │
└──────────────────────────┘

┌──────────────────────────┐
│   TicketCache            │
├──────────────────────────┤
│ - _cache: Dict           │
│ - _hit_count             │
│ - _miss_count            │
├──────────────────────────┤
│ + get()                  │
│ + put()                  │
│ + exists()               │
│ + get_stats()            │
└──────────────────────────┘

┌──────────────────────────┐
│   SystemLogger           │
├──────────────────────────┤
│ - log_file: Path         │
├──────────────────────────┤
│ + log_create()           │
│ + log_transition()       │
│ + log_delete()           │
│ + log_cache_hit/miss()   │
└──────────────────────────┘
```

---

## Performance Characteristics

### Time Complexity
- **Create Ticket**: O(1) - hash insertion
- **Get Ticket (Cache Hit)**: O(1) - hash lookup
- **Get Ticket (Cache Miss)**: O(1)* - JSON file I/O (fast for small files)
- **Search by Status**: O(n) - linear scan of cache
- **Delete Ticket**: O(1) - hash deletion

### Space Complexity
- **Cache**: O(n) - stores all tickets in memory
- **Database**: O(n) - JSON file for all tickets
- **Total**: O(2n) ≈ O(n) for typical usage

### I/O Operations
- **Create**: 1 database write
- **View**: 0 (after first cache miss)
- **Transition**: 1 database write
- **Delete**: 1 database write

---

## Resilience Features

### Crash Recovery
✓ All changes saved to database.json immediately
✓ On restart, all data restored from file
✓ Cache repopulated on startup
✓ Zero data loss guaranteed

### Error Handling
✓ Invalid transitions blocked with error messages
✓ Input validation prevents malformed data
✓ File I/O errors caught and logged
✓ Graceful degradation on failures

### Data Validation
✓ JSON format validated on load
✓ Corrupted database automatically recovered
✓ State machine prevents logical inconsistencies
✓ Timestamp tracking for audit trail

---

## Extensibility Points

For future enhancements:
1. **Database**: Replace JSON with SQL/NoSQL
2. **Cache**: Implement LRU eviction, persistence
3. **Search**: Add complex query builders
4. **Logging**: Send logs to external service
5. **UI**: Replace console with web/GUI
6. **Workflow**: Add more stages or branching logic

---

**This architecture ensures**: Reliability, Maintainability, Scalability, and Security
