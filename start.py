"""
Console-based Concert Ticket Management System
Main entry point with user-friendly menu interface
"""
from ticket_system import TicketManagementSystem
from ticket import Ticket


def clear_screen():
    """Clear console screen."""
    import os
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    """Print system header."""
    print("\n" + "="*70)
    print(" "*15 + "CONCERT TICKET MANAGEMENT SYSTEM")
    print("="*70)


def print_menu():
    """Display main menu."""
    print("\n" + "-"*70)
    print("MAIN MENU")
    print("-"*70)
    print("1. Create New Ticket")
    print("2. View Ticket Details")
    print("3. Update Ticket Status")
    print("4. Search Tickets")
    print("5. View All Tickets")
    print("6. Delete Ticket")
    print("7. View System Statistics")
    print("8. View Recent Logs")
    print("9. Exit")
    print("-"*70)


def print_ticket(ticket):
    """Pretty print a ticket."""
    print(f"\n  Ticket ID: {ticket.ticket_id}")
    print(f"  Customer: {ticket.customer_name}")
    print(f"  Concert: {ticket.concert_name}")
    print(f"  Price: ${ticket.price:.2f}")
    print(f"  Status: {ticket.status}")
    print(f"  Timestamps:")
    for stage, timestamp in ticket.timestamps.items():
        print(f"    - {stage}: {timestamp}")


def print_tickets_table(tickets):
    """Print tickets in table format."""
    if not tickets:
        print("\nNo tickets found.")
        return
    
    print("\n" + "-"*110)
    print(f"{'ID':<12} {'Status':<12} {'Customer':<20} {'Concert':<30} {'Price':<10}")
    print("-"*110)
    
    for ticket in tickets:
        print(f"{ticket.ticket_id:<12} {ticket.status:<12} {ticket.customer_name:<20} "
              f"{ticket.concert_name:<30} ${ticket.price:<9.2f}")
    print("-"*110)


def create_ticket_menu(system):
    """Handle ticket creation."""
    try:
        print("\n" + "="*70)
        print("CREATE NEW TICKET")
        print("="*70)
        
        ticket_id = input("Enter Ticket ID: ").strip()
        if not ticket_id:
            print("Error: Ticket ID cannot be empty")
            return
        
        # Check if ID already exists
        if system.database.ticket_exists(ticket_id):
            print(f"\n✗ Error: Ticket ID '{ticket_id}' is already used!")
            print("  Please use a different Ticket ID")
            return
        
        customer_name = input("Enter Customer Name: ").strip()
        if not customer_name:
            print("Error: Customer name cannot be empty")
            return
        
        concert_name = input("Enter Concert Name: ").strip()
        if not concert_name:
            print("Error: Concert name cannot be empty")
            return
        
        try:
            price = float(input("Enter Ticket Price ($): "))
            if price <= 0:
                print("Error: Price must be positive")
                return
        except ValueError:
            print("Error: Price must be a valid number")
            return
        
        success, message = system.create_ticket(ticket_id, customer_name, concert_name, price)
        
        if success:
            print(f"\n✓ {message}")
        else:
            print(f"\n✗ {message}")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        return


def view_ticket_menu(system):
    """Handle viewing ticket details."""
    try:
        print("\n" + "="*70)
        print("VIEW TICKET DETAILS")
        print("="*70)
        
        ticket_id = input("Enter Ticket ID: ").strip()
        if not ticket_id:
            print("Error: Ticket ID cannot be empty")
            return
        
        ticket = system.get_ticket(ticket_id)
        
        if ticket:
            print_ticket(ticket)
        else:
            print(f"\n✗ Ticket {ticket_id} not found")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        return


def select_ticket_with_pagination(system):
    """
    Display tickets with pagination and allow user to select one.
    Returns ticket_id if selected, None if cancelled.
    """
    all_tickets = system.get_all_tickets()
    
    if not all_tickets:
        print("\n✗ No tickets found in the system")
        return None
    
    page_size = 5
    total_pages = (len(all_tickets) + page_size - 1) // page_size
    current_page = 0
    
    while True:
        # Calculate start and end indices for current page
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(all_tickets))
        page_tickets = all_tickets[start_idx:end_idx]
        
        # Display tickets on current page
        print("\n" + "-"*110)
        print(f"Tickets (Page {current_page + 1}/{total_pages}) - Showing {len(page_tickets)} of {len(all_tickets)} tickets")
        print("-"*110)
        
        for idx, ticket in enumerate(page_tickets, 1):
            print(f"  {idx} - ID: {ticket.ticket_id:<12} Status: {ticket.status:<12} "
                  f"Customer: {ticket.customer_name:<20} Concert: {ticket.concert_name:<30}")
        
        print("-"*110)
        
        # Navigation instructions
        nav_options = []
        if current_page > 0:
            nav_options.append("'p' for Previous")
        if current_page < total_pages - 1:
            nav_options.append("'n' for Next")
        
        print(f"Options: Enter Ticket ID (1-{len(page_tickets)}), {', '.join(nav_options) if nav_options else 'At first/last page'}")
        print("         Or type full Ticket ID, or 'q' to Go back")
        print("-"*110)
        
        try:
            user_input = input("Your choice: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return None
        
        if user_input == 'q':
            return None
        elif user_input == 'n' and current_page < total_pages - 1:
            current_page += 1
            continue
        elif user_input == 'p' and current_page > 0:
            current_page -= 1
            continue
        elif user_input in ['n', 'p']:
            print("✗ Cannot navigate further in that direction")
            continue
        else:
            # Try to handle numeric input (1-5)
            try:
                choice_num = int(user_input)
                if 1 <= choice_num <= len(page_tickets):
                    selected_ticket = page_tickets[choice_num - 1]
                    return selected_ticket.ticket_id
                else:
                    print("✗ Invalid selection number")
                    continue
            except ValueError:
                # Try as full ticket ID
                if system.database.ticket_exists(user_input):
                    return user_input
                else:
                    print(f"✗ Ticket ID '{user_input}' not found")
                    continue


def update_ticket_menu(system):
    """Handle ticket status update."""
    try:
        print("\n" + "="*70)
        print("UPDATE TICKET STATUS")
        print("="*70)
        
        # Use pagination to select ticket
        ticket_id = select_ticket_with_pagination(system)
        
        if not ticket_id:
            return
        
        ticket = system.get_ticket(ticket_id)
        if not ticket:
            print(f"\n✗ Ticket {ticket_id} not found")
            return
        
        print(f"\nCurrent Status: {ticket.status}")
        print("-" * 70)
        
        # Get valid transitions for current status
        valid_transitions = Ticket.VALID_TRANSITIONS.get(ticket.status, [])
        
        if not valid_transitions:
            print(f"\n✗ Ticket is in final stage ({ticket.status}) and cannot be modified")
            return
        
        # Display options
        print("Select new status:")
        for idx, status in enumerate(valid_transitions, 1):
            print(f"  {idx} - Change to {status}")
        print(f"  {len(valid_transitions) + 1} - Go back")
        print("-" * 70)
        
        try:
            choice = input("Enter your choice: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return
        
        try:
            choice_num = int(choice)
        except ValueError:
            print("Error: Please enter a valid number")
            return
        
        # Check if user wants to go back
        if choice_num == len(valid_transitions) + 1:
            return
        
        # Validate choice
        if choice_num < 1 or choice_num > len(valid_transitions):
            print("Error: Invalid choice")
            return
        
        new_status = valid_transitions[choice_num - 1]
        success, message = system.transition_ticket(ticket_id, new_status)
        
        if success:
            print(f"\n✓ {message}")
        else:
            print(f"\n✗ {message}")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        return


def search_tickets_menu(system):
    """Handle ticket search."""
    try:
        print("\n" + "="*70)
        print("SEARCH TICKETS")
        print("="*70)
        print("\nSearch by:")
        print("1. Ticket ID")
        print("2. Status")
        print("3. Customer Name")
        print("4. Concert Name")
        print("5. Back to Main Menu")
        print("-"*70)
        
        choice = input("Select search type (1-5): ").strip()
        
        if choice == "1":
            ticket_id = input("Enter Ticket ID: ").strip()
            ticket = system.search_by_id(ticket_id)
            if ticket:
                print_ticket(ticket)
            else:
                print(f"\n✗ No ticket found with ID: {ticket_id}")
        
        elif choice == "2":
            print(f"Valid statuses: {', '.join(Ticket.STAGES)}")
            status = input("Enter Status: ").strip()
            tickets = system.search_by_status(status)
            if tickets:
                print_tickets_table(tickets)
            else:
                print(f"\n✗ No tickets found with status: {status}")
        
        elif choice == "3":
            customer_name = input("Enter Customer Name (partial match): ").strip()
            tickets = system.search_by_customer(customer_name)
            if tickets:
                print_tickets_table(tickets)
            else:
                print(f"\n✗ No tickets found for customer: {customer_name}")
        
        elif choice == "4":
            concert_name = input("Enter Concert Name (partial match): ").strip()
            tickets = system.search_by_concert(concert_name)
            if tickets:
                print_tickets_table(tickets)
            else:
                print(f"\n✗ No tickets found for concert: {concert_name}")
        
        elif choice == "5":
            return
        else:
            print("Invalid choice")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        return


def view_all_tickets_menu(system):
    """Display all tickets."""
    print("\n" + "="*70)
    print("ALL TICKETS")
    print("="*70)
    
    tickets = system.get_all_tickets()
    print_tickets_table(tickets)


def delete_ticket_menu(system):
    """Handle ticket deletion."""
    try:
        print("\n" + "="*70)
        print("DELETE TICKET")
        print("="*70)
        
        ticket_id = input("Enter Ticket ID to delete: ").strip()
        if not ticket_id:
            print("Error: Ticket ID cannot be empty")
            return
        
        confirm = input(f"Are you sure you want to delete ticket {ticket_id}? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Deletion cancelled")
            return
        
        success, message = system.delete_ticket(ticket_id)
        
        if success:
            print(f"\n✓ {message}")
        else:
            print(f"\n✗ {message}")
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled.")
        return


def view_statistics_menu(system):
    """Display system statistics."""
    print("\n" + "="*70)
    print("SYSTEM STATISTICS")
    print("="*70)
    
    stats = system.get_cache_stats()
    
    print(f"\nCache Performance:")
    print(f"  Cache Hits: {stats['hits']}")
    print(f"  Cache Misses: {stats['misses']}")
    print(f"  Total Requests: {stats['total_requests']}")
    print(f"  Hit Rate: {stats['hit_rate_percent']}%")
    print(f"  Cached Items: {stats['cached_items']}")
    
    all_tickets = system.get_all_tickets()
    print(f"\nTicket Statistics:")
    print(f"  Total Tickets: {len(all_tickets)}")
    
    # Count by status
    status_counts = {}
    for ticket in all_tickets:
        status_counts[ticket.status] = status_counts.get(ticket.status, 0) + 1
    
    for status in Ticket.STAGES:
        count = status_counts.get(status, 0)
        print(f"    {status}: {count}")


def view_logs_menu():
    """Display recent log entries."""
    print("\n" + "="*70)
    print("RECENT LOG ENTRIES (Last 30)")
    print("="*70)
    
    try:
        with open("log.txt", "r") as f:
            lines = f.readlines()
            recent_lines = lines[-30:] if len(lines) > 30 else lines
            for line in recent_lines:
                print(line.rstrip())
    except FileNotFoundError:
        print("\nNo log file found yet.")


def main():
    """Main application loop."""
    system = TicketManagementSystem()
    
    try:
        while True:
            print_header()
            print_menu()
            
            try:
                choice = input("Select an option (1-9): ").strip()
            except KeyboardInterrupt:
                print("\n\n" + "="*70)
                print("User interrupted - Exiting system")
                print("="*70)
                system.shutdown()
                break
            except EOFError:
                print("\n\n" + "="*70)
                print("End of input - Exiting system")
                print("="*70)
                system.shutdown()
                break
            
            if choice == "1":
                create_ticket_menu(system)
            elif choice == "2":
                view_ticket_menu(system)
            elif choice == "3":
                update_ticket_menu(system)
            elif choice == "4":
                search_tickets_menu(system)
            elif choice == "5":
                view_all_tickets_menu(system)
            elif choice == "6":
                delete_ticket_menu(system)
            elif choice == "7":
                view_statistics_menu(system)
            elif choice == "8":
                view_logs_menu()
            elif choice == "9":
                print("\n" + "="*70)
                print("Thank you for using Concert Ticket Management System!")
                print("="*70)
                system.shutdown()
                break
            else:
                print("Invalid choice. Please try again.")
            
            if choice != "9":
                try:
                    input("\nPress Enter to continue...")
                except KeyboardInterrupt:
                    print("\n\n" + "="*70)
                    print("User interrupted - Exiting system")
                    print("="*70)
                    system.shutdown()
                    break
                except EOFError:
                    pass
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        system.shutdown()
        raise


if __name__ == "__main__":
    main()

