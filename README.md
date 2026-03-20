# Tasklings

A family chore management app with a gamified reward system. Children complete daily chores to earn **Lumins** — a virtual currency they can spend in a family-run store on real rewards.

Works as a Progressive Web App (PWA): install it on any phone or tablet and it works offline too.

---

## What It Does

- **Parents** set up chores, define rewards in a store, and verify when kids finish their work
- **Children** see their daily task list, check off chores, earn Lumins, and spend them on rewards
- **Quests** let parents create multi-step challenges — solo or group — with bonus Lumins on completion
- **Rotating chores** automatically cycle between kids on a daily, weekly, or monthly schedule
- **Offline support** means chores can be marked complete even without an internet connection; they sync when back online

---

## Getting Started

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Install

```bash
git clone <repo-url>
cd tasklings
uv sync
```

### Configure

```bash
cp .env.example .env
```

Open `.env` and set a unique secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output as the value of `SECRET_KEY` in `.env`. Everything else works out of the box for a home network setup.

### Run

```bash
uv run serve
```

The app starts at `http://localhost:5000`. To make it accessible to other devices on your network:

```bash
uv run serve --host 0.0.0.0 --port 5000
```

Then open `http://<your-computer's-ip>:5000` on any phone, tablet, or browser in the house.

### First Login

The default admin account is created automatically:

| Username | Password  |
|----------|-----------|
| `admin`  | `changeme` |

**Change this immediately** after your first login via the Profile page or:

```bash
uv run reset-admin --username admin --password your-new-password
```

---

## Install on Your Phone (PWA)

Tasklings is a Progressive Web App — you can add it to the home screen and it will look and feel like a native app.

**iOS (Safari):** Open the app → tap the Share button → "Add to Home Screen"
**Android (Chrome):** Open the app → tap the three-dot menu → "Add to Home Screen" or "Install App"

Once installed, the app works offline. Any chores marked complete while offline will sync automatically when you reconnect.

---

## Parent Setup Guide

### 1. Add Your Kids

Go to **Admin → Members** and create an account for each child. They'll use a username and password to log in.

### 2. Define Chores

Go to **Admin → Chores** and add the chores your household needs. For each chore you set:

- **Title & description** — what needs to be done
- **Lumin value** — how many Lumins it's worth
- **Type:**
  - *Constant* — appears on the same person's list every day
  - *Rotating* — cycles through all family members on a schedule you choose (daily, weekly, or monthly)

### 3. Set Up the Store

Go to **Admin → Store** and create items kids can buy with their Lumins. Each item has:

- A name, price, and optional stock limit
- Optional **per-member visibility** — hide items from specific kids or make items only available to certain children

### 4. Create Quests (Optional)

Quests are bonus challenges on top of daily chores.

- **Solo quests** — a series of chores assigned to one child, with a Lumin bonus when all are complete
- **Group quests** — shared challenges where multiple kids each claim and complete chores from a shared pool; everyone earns the bonus on completion

Go to **Admin → Quests** to create them.

### 5. Verify Completed Chores

When a child marks a chore as done, it shows as pending verification. You verify it from the **Admin dashboard** or the runlist — this is when Lumins are actually awarded.

---

## Child User Guide

### Your Daily Runlist

Log in and you'll land on your **Runlist** — today's chores assigned to you. Tap a chore to mark it complete. Your parent will verify it and you'll earn your Lumins.

### Earning Lumins

Lumins are awarded when a parent verifies your completed chore. You can see your balance at any time on your **Profile** page.

### The Store

Go to the **Store** to browse rewards available to you. If you have enough Lumins, tap an item to buy it. Your balance updates immediately and your parent can see the purchase.

### Quests

Check the **Quests** section for any special challenges. For group quests, tap to join, then claim chores from the shared pool and complete them.

### Your Profile

Visit **Profile** to:
- See your Lumin balance and transaction history
- View your purchase history
- Update your name, avatar, or color
- Change your password

---

## Configuration Reference

All settings live in your `.env` file.

| Setting | Default | Description |
|---------|---------|-------------|
| `SECRET_KEY` | *(required)* | Secret used to sign session cookies — generate a random one |
| `DATABASE_PATH` | `tasklings.db` | Where the SQLite database file is stored |
| `SESSION_LIFETIME_HOURS` | `72` | How long a login session lasts before expiring |
| `HOUSEHOLD_TIMEZONE` | `America/Chicago` | Your timezone — affects when "today's" chores reset |
| `BCRYPT_ROUNDS` | `12` | Password hashing strength (higher = slower but more secure) |
| `COOKIE_SECURE` | `false` | Set to `true` if serving over HTTPS |
| `SMTP_HOST` | *(empty)* | Optional: SMTP server for password reset emails |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` | *(empty)* | SMTP login |
| `SMTP_PASSWORD` | *(empty)* | SMTP password |
| `SMTP_FROM` | *(empty)* | From address for reset emails |

**Important:** Set `HOUSEHOLD_TIMEZONE` to your local IANA timezone (e.g. `America/New_York`, `Europe/London`, `America/Los_Angeles`) so chores reset at midnight your time.

---

## Password Resets

**If SMTP is configured:** Kids can request a password reset from the login page and receive an email with a reset link.

**Without SMTP:** Parents can generate a reset token from the Admin dashboard and share it directly with the child.

---

## Running Tests

```bash
pytest
pytest tests/test_auth.py -v    # specific file
pytest -k "test_login"          # specific test by name
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python / [Quart](https://quart.palletsprojects.com/) (async) |
| Database | SQLite (via aiosqlite) |
| Templates | Jinja2 + HTMX |
| Frontend | Vanilla JS, custom CSS |
| Offline | Service Worker + IndexedDB |
| Package manager | [uv](https://docs.astral.sh/uv/) |
