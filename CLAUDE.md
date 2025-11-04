# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based web application for managing bingo event sales (Sistema de Vendas Online de Bingo). It handles customer management, event creation, ticket sales, and collaborator access control with role-based permissions.

## Technology Stack

- **Backend**: Flask (Python web framework)
- **Database**: MongoDB Atlas (cloud-hosted)
- **Authentication**: bcrypt for password hashing
- **Session Management**: Flask sessions with 60-minute timeout

## Development Commands

### Installation
```bash
pip install -r requirements.txt
```

### Running the Application
```bash
python app.py
```
The app runs on `http://0.0.0.0:5001` by default.

### Dependencies
- Flask
- pymongo
- bcrypt (for password hashing)
- python-dotenv (optional, for environment variables)

## Architecture & Key Concepts

### Database Structure

**MongoDB Database**: `bingo_vendas_db`

**Collections**:
- `colaboradores` - Staff users with access levels 1-3
- `clientes` - Customers who purchase tickets
- `eventos` - Bingo events with prize configuration
- `vendas{id_evento}` - Dynamic collections per event (e.g., `vendas1`, `vendas2`)
- `controle_venda` - Atomic ticket numbering control per event
- `contadores` - Global sequence generators for IDs
- `parametros` - Global configuration (URLs, room names)

### Sequential ID System

The app uses **integer sequential IDs** (not MongoDB ObjectIDs) for user-facing entities:
- Clients: `id_cliente` (INT)
- Collaborators: `id_colaborador` (INT)
- Events: `id_evento` (INT)
- Sales: `id_venda` formatted as `V{number:05d}` (e.g., V00001)

**Critical**: All sequence generation uses **atomic operations** with `find_one_and_update` on the `contadores` collection to prevent race conditions. See functions:
- `get_next_global_sequence()` (app.py:88)
- `get_next_cliente_sequence()` (app.py:109)
- `get_next_colaborador_sequence()` (app.py:118)
- `get_next_evento_sequence()` (app.py:130)

### Thread-Safe Ticket Numbering

**Critical for Sales Integrity**: Ticket numbering uses locks and atomic operations:
- `venda_lock`, `cliente_lock`, `colaborador_lock`, `evento_lock` (app.py:41-46)
- `get_next_bilhete_sequence()` (app.py:142) implements rollover logic when ticket numbers reach `numero_maximo` (default: 72000)
- The function returns the **current** sequence value and atomically increments for the next sale

### Access Control System

**Decorator**: `@login_required` (app.py:49)

**User Levels**:
- Level 0: Clientes (customers) - dashboard access only
- Level 1: Colaboradores (basic staff) - sales operations
- Level 2: Colaboradores (advanced staff) - sales + client management
- Level 3: Colaboradores (admin) - full access including collaborator/event management

**Session Variables**:
- `logged_in`, `id_colaborador`/`id_cliente`, `nivel`, `nick`

### Data Type Handling

**Critical**: MongoDB stores prices using `Decimal128` to preserve precision. Always use:
- `safe_float()` (app.py:71) to convert Decimal128 → float for Jinja templates
- `Decimal128(str(value))` when storing monetary values

### Password Management

- Passwords are hashed with bcrypt before storage
- **Client passwords**: Default to capitalized nick if not specified (app.py:1239)
- **Login formatting**: Passwords are capitalized before bcrypt verification (app.py:325)
- **Special user**: `TECBIN` collaborator cannot be deleted (app.py:692)

### Event Status Workflow

Events have three statuses:
- `paralizado` - Initial state, sales disabled
- `ativo` - Sales enabled, appears in sales interface
- `finalizado` - Event completed

When activated, `data_ativado` timestamp is set.

### Sales Transaction Flow

1. Client selects event and quantity
2. System acquires `venda_lock` for atomicity (app.py:938)
3. Generates sequential sale ID from global counter
4. Atomically retrieves and increments ticket number range via `get_next_bilhete_sequence()`
5. Handles rollover if ticket numbers exceed `numero_maximo`
6. Creates sale record in event-specific collection `vendas{id_evento}`
7. Updates client's `data_ultimo_compra`
8. Displays receipt with ticket number ranges

**Critical**: The entire process is wrapped in a lock timeout to prevent concurrent sales corruption.

## File Structure

- `app.py` - Monolithic Flask application with all routes and business logic
- `templates/` - Jinja2 HTML templates
  - `base.html` - Base template with common layout
  - `index.html` - Login page
  - `menu.html` - Main menu (role-based)
  - `venda.html` - Sales interface
  - `cadastro_cliente.html` - Client CRUD
  - `cadastro_colaborador.html` - Collaborator CRUD
  - `cadastro_evento.html` - Event CRUD
  - `consulta_status_eventos.html` - Event sales dashboard
- `static/` - CSS and JavaScript assets
- `requirements.txt` - Python dependencies

## Important Implementation Notes

### MongoDB Connection
- Uses global client `client_global` with 1-second timeout for fast failure (app.py:33)
- Connection status checked via `g.db_status` in `before_request` hook (app.py:262)
- If DB is offline, user operations gracefully fail with error messages

### Date/Time Handling
- Events store dates as strings in DD/MM/YYYY format (converted from HTML YYYY-MM-DD)
- Sales transactions use `datetime.utcnow()` for timestamps
- Event sorting uses `data_hora_evento` datetime field (app.py:1491)

### Form Data Validation
- CPF validation with check digits (app.py:225)
- Phone/CPF cleaning removes non-numeric characters (app.py:220)
- Names are title-cased automatically (app.py:215)
- PIX key confirmation required (app.py:584, 1209)

### Security Considerations
- Secret key is hardcoded (app.py:21) - **should be moved to environment variable**
- MongoDB password is URL-encoded but visible in code (app.py:26) - **should use environment variable**
- Session lifetime is 60 minutes (app.py:22)
- Admin cannot delete themselves or lower their own level if they're the only admin (app.py:635)

## Common Development Tasks

### Adding a New Route
1. Define route function with `@app.route()` decorator
2. Add `@login_required` if authentication needed
3. Check `g.db_status` before DB operations
4. Use `safe_float()` for any Decimal128 values passed to templates
5. Handle errors with redirects and flash messages via query params

### Modifying Database Schema
- Update relevant document construction in `gravar_*` functions
- Add field conversions in display routes if using Decimal128
- Consider backward compatibility with existing documents

### Testing Sales Atomicity
- Test concurrent sales with multiple browser tabs/users
- Verify no duplicate ticket numbers are issued
- Check rollover behavior near `numero_maximo` boundary
