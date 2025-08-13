# 🛠️ Apartment Discord Bot – Command Reference

This bot helps manage daily apartment life including chores, reminders, groceries, bills, and activities. Use the following slash commands to automate and organize tasks.

---

## 📅 Scheduling & Reminders

### `/reminders @user "message" <time> <date>`

Creates a reminder that pings the user at regular intervals leading up to the deadline.  
**Example:**  
`/reminders @stephanie "Don't forget to ship the return packages" 3pm 8/8/25`

### `/schedule "event name" <date> <time> [@participants]`

Creates a Google Calendar invite and notifies the participants.  
**Example:**  
`/schedule "Dinner with landlord" 8/10/25 6pm @david @stephanie`

---

## 🧹 Chores & Tasks

### `/chore <frequency> "chore name" [random]`

Assigns a chore at a given frequency (`week`, `month`, etc). If `random` is specified, the assignee is chosen randomly. The chore load is split evenly over time.  
**Example:**  
`/chore month "Clean sink" random`

### `/task @user "task description"`

Creates an ad-hoc task and assigns it to the tagged user.  
**Example:**  
`/task @david "Fix the door"`

---

## 🛒 Groceries & Shopping

### `/groceries "item name"`

Adds an item to the grocery list. The list is refreshed when `/groceries bought` or a similar command is used.  
**Example:**  
`/groceries "Sesame Oil"`

### `/shopping_list "item name"`

Adds a general (non-food) item to the shopping list for everyone to see.  
**Example:**  
`/shopping_list "Scissors"`

---

## 💸 Budgeting & Bills

### `/budget`

Parses Chase statements and compares actual spending to an externally defined proposed budget.  
**Note:** Requires linking or uploading the bank statement file.

### `/venmo @user <amount>`

Used to calculate and display how much each person owes at the start of the month, including rent and shared expenses.  
**Example:**  
`/venmo @stephanie 1345`

---

## 🍽️ Food & Entertainment

### `/restaurant <food> <center> <radius>`

Finds a restaurant using Google Maps API based on food type, location, and search radius.  
**Example:**  
`/restaurant sushi "Astoria NY" 2km`

### `/activity`

Finds a random activity happening in New York that day using an events API (e.g. Eventbrite, Meetup).  
**Example:**  
`/activity`

---

## 🔧 Utilities

### `/wifi`

Displays the apartment's WiFi network name and password for quick access.  
**Example:**  
`/wifi`

### `/lost_item "item name"`

Adds an item to the list of lost items so everyone is aware and can help find it.  
**Example:**  
`/lost_item "TV remote"`

### `/quote "quote text"`

Adds a quote to the apartment memory log for fun moments.  
**Example:**  
`/quote "You better cook with love" - David`

---

## 🔁 Recurring System Tasks

The bot also supports recurring reminders:

- Rent due on the **1st of every month**
- Bill reminders with customizable due dates
