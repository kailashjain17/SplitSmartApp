# SplitSmartApp

A simple, terminal-based expense splitter to manage shared expenses, track who owes whom, and settle up easily — all without depending on any online service.

## ✨ Features

* Add users and create groups.
* Record expenses with multiple split types:

  * **Equal Split** – everyone pays the same.
  * **Unequal Split** – specify exact amounts per person.
  * **Percent Split** – divide by percentage.
  * **Shares Split** – divide in ratio of given shares.
* Automatically calculates and simplifies debts between members.
* View outstanding balances in plain text.
* Record settlements between users.
* Save and load all data to/from a JSON file.

## 🧠 How It Works

Each expense is stored with its participants, payer, and chosen split strategy.
The app maintains a minimal debt graph, simplifying who owes whom — so if A owes B and B owes C, it directly figures out that A should pay C.

## 🚀 Getting Started

### 1. Run the app

```bash
python splitsmart.py
```

### 2. Use the menu

You’ll get a simple CLI menu to:

1. Add users
2. Create a group
3. Add expenses
4. View debts
5. Record settlements
6. Save/Load data

Example flow:

```
SplitSmart Menu
1. Add User
2. Create Group
3. Add Expense
4. View Debts
5. Settle Up
6. Save / Load Data
7. Exit
```

## 💾 Data Persistence

All data is stored in a JSON file using the **Save/Load Data** option — so you can resume where you left off.

## 📂 File Structure

```
splitsmart.py      # Main application
data.json          # (optional) saved users, groups, and debts
```

## 🧩 Requirements

* Python 3.9 or above
* No external dependencies — works out of the box.

## 💡 Example Use Case

Perfect for roommates, college trips, group dinners, or any shared spending situation.
