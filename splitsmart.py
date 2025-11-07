from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional, Protocol
import json
import sys


# ================ Domain Model ================

@dataclass(eq=True, frozen=True)
class User:
    name: str
    email: str

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

class SplitStrategy(Protocol):
    def calculate_shares(
        self,
        amount: float,
        participants: List[User],
        details: Optional[dict] = None
    ) -> Dict[User, float]:
        ...

class EqualSplit:
    """Split amount equally among participants (rounded to 2 decimals; last gets remainder)."""

    def calculate_shares(
        self,
        amount: float,
        participants: List[User],
        details: Optional[dict] = None
    ) -> Dict[User, float]:
        n = len(participants)
        if n == 0:
            raise ValueError("No participants to split among.")
        base = round(amount / n, 2)
        shares = {p: base for p in participants}
        # Adjust rounding remainder
        distributed = round(sum(shares.values()), 2)
        remainder = round(amount - distributed, 2)
        if remainder != 0:
            # Give remainder to the payer if in list, else to first (will be reassigned by caller if needed)
            shares[participants[0]] = round(shares[participants[0]] + remainder, 2)
        return shares

class UnequalSplit:
    """Explicit amounts per participant via details={'amounts': {email: value, ...}} that sum to total."""

    def calculate_shares(
        self,
        amount: float,
        participants: List[User],
        details: Optional[dict] = None
    ) -> Dict[User, float]:
        if not details or "amounts" not in details:
            raise ValueError("UnequalSplit requires details['amounts'].")
        # Map emails to users
        email_to_user = {u.email: u for u in participants}
        amounts: Dict[str, float] = details["amounts"]
        # Validate coverage
        if set(amounts.keys()) != set(email_to_user.keys()):
            missing = set(email_to_user.keys()) - set(amounts.keys())
            extra = set(amounts.keys()) - set(email_to_user.keys())
            raise ValueError(f"Amounts keys must match participants emails. Missing={missing}, Extra={extra}")
        # Validate sum
        total = round(sum(amounts.values()), 2)
        if round(amount, 2) != total:
            raise ValueError(f"Amounts must sum to total: {total} != {round(amount,2)}")
        return {email_to_user[e]: round(v, 2) for e, v in amounts.items()}

class PercentSplit:
    """Percentages per participant via details={'percents': {email: percent (0-100)}} sum to 100."""

    def calculate_shares(
        self,
        amount: float,
        participants: List[User],
        details: Optional[dict] = None
    ) -> Dict[User, float]:
        if not details or "percents" not in details:
            raise ValueError("PercentSplit requires details['percents'].")
        email_to_user = {u.email: u for u in participants}
        percents: Dict[str, float] = details["percents"]
        if set(percents.keys()) != set(email_to_user.keys()):
            missing = set(email_to_user.keys()) - set(percents.keys())
            extra = set(percents.keys()) - set(email_to_user.keys())
            raise ValueError(f"Percents keys must match participants emails. Missing={missing}, Extra={extra}")
        total_pct = round(sum(percents.values()), 6)
        if abs(total_pct - 100.0) > 1e-6:
            raise ValueError(f"Percents must sum to 100, got {total_pct}")
        # Compute rounded shares, fix rounding by assigning remainder to the first
        shares = {}
        running = 0.0
        for i, (email, pct) in enumerate(percents.items()):
            share = round(amount * (pct / 100.0), 2)
            shares[email] = share
            running += share
        remainder = round(amount - round(running, 2), 2)
        if remainder != 0:
            first_key = next(iter(percents.keys()))
            shares[first_key] = round(shares[first_key] + remainder, 2)
        return {email_to_user[e]: v for e, v in shares.items()}

class SharesSplit:
    """Integer 'shares' per participant via details={'shares': {email: int}} split in ratio of shares."""

    def calculate_shares(
        self,
        amount: float,
        participants: List[User],
        details: Optional[dict] = None
    ) -> Dict[User, float]:
        if not details or "shares" not in details:
            raise ValueError("SharesSplit requires details['shares'].")
        email_to_user = {u.email: u for u in participants}
        shares_map: Dict[str, int] = details["shares"]
        if set(shares_map.keys()) != set(email_to_user.keys()):
            missing = set(email_to_user.keys()) - set(shares_map.keys())
            extra = set(shares_map.keys()) - set(email_to_user.keys())
            raise ValueError(f"Shares keys must match participants emails. Missing={missing}, Extra={extra}")
        total_shares = sum(int(v) for v in shares_map.values())
        if total_shares <= 0:
            raise ValueError("Total shares must be positive.")
        shares = {}
        running = 0.0
        for email, s in shares_map.items():
            part = round(amount * (int(s) / total_shares), 2)
            shares[email] = part
            running += part
        remainder = round(amount - round(running, 2), 2)
        if remainder != 0:
            first_key = next(iter(shares_map.keys()))
            shares[first_key] = round(shares[first_key] + remainder, 2)
        return {email_to_user[e]: v for e, v in shares.items()}

@dataclass
class Expense:
    description: str
    amount: float
    payer: User
    participants: List[User]
    strategy_name: str
    details: Optional[dict] = None

    def calculate_splits(self) -> Dict[User, float]:
        strategy = strategy_from_name(self.strategy_name)
        return strategy.calculate_shares(self.amount, self.participants, self.details)

def strategy_from_name(name: str) -> SplitStrategy:
    key = name.strip().lower()
    if key in ("equal",):
        return EqualSplit()
    if key in ("unequal", "amounts"):
        return UnequalSplit()
    if key in ("percent", "percentage", "percents"):
        return PercentSplit()
    if key in ("shares", "ratio"):
        return SharesSplit()
    raise ValueError(f"Unknown split type '{name}'")

# ================ Debt Manager ================

class DebtManager:
    """
    Track directed debts as map[(debtor_email, creditor_email)] = amount (>0).
    Provides simplification via netting balances.
    """

    def __init__(self) -> None:
        self.debts: Dict[Tuple[str, str], float] = {}

    def _add_debt(self, debtor: User, creditor: User, amount: float) -> None:
        if debtor.email == creditor.email:
            return
        key = (debtor.email, creditor.email)
        self.debts[key] = round(self.debts.get(key, 0.0) + amount, 2)
        if self.debts[key] <= 0.009:
            self.debts.pop(key, None)

    def update_debts_for_expense(self, expense: Expense) -> None:
        splits = expense.calculate_splits()
        payer = expense.payer
        for participant, share in splits.items():
            if participant.email == payer.email:
                continue
            self._add_debt(participant, payer, share)
        self.simplify_debts()

    def settle_up(self, payer: User, receiver: User, amount: float) -> None:
        """Record payment from payer to receiver reducing payer->receiver debt; if inverted, it creates reverse debt reduction."""
        key = (payer.email, receiver.email)
        if key not in self.debts:
            # If there is opposite debt, paying still makes sense (it increases opposite)
            opp_key = (receiver.email, payer.email)
            if opp_key in self.debts:
                # paying receiver when receiver actually owes payer increases receiver's debt
                self.debts[opp_key] = round(self.debts[opp_key] + amount, 2)
            else:
                # No prior debt; treat as overpayment -> creates reverse credit
                self.debts[opp_key] = round(amount, 2)
        else:
            self.debts[key] = round(self.debts[key] - amount, 2)
            if self.debts[key] <= 0.009:
                self.debts.pop(key, None)
        self.simplify_debts()

    def simplify_debts(self) -> None:
        """Convert pairwise debts to minimal transfers using net balances."""
        # Compute net balance per user
        net: Dict[str, float] = {}
        for (debtor, creditor), amt in self.debts.items():
            net[debtor] = round(net.get(debtor, 0.0) - amt, 2)
            net[creditor] = round(net.get(creditor, 0.0) + amt, 2)

        debtors = [(u, -bal) for u, bal in net.items() if bal < -0.009]
        creditors = [(u, bal) for u, bal in net.items() if bal > 0.009]
        debtors.sort(key=lambda x: x[1], reverse=False)
        creditors.sort(key=lambda x: x[1], reverse=False)

        simplified: Dict[Tuple[str, str], float] = {}
        i = j = 0
        while i < len(debtors) and j < len(creditors):
            d_email, d_amt = debtors[i]
            c_email, c_amt = creditors[j]
            pay = round(min(d_amt, c_amt), 2)
            if pay > 0:
                simplified[(d_email, c_email)] = round(simplified.get((d_email, c_email), 0.0) + pay, 2)
            d_amt = round(d_amt - pay, 2)
            c_amt = round(c_amt - pay, 2)
            if d_amt <= 0.009:
                i += 1
            else:
                debtors[i] = (d_email, d_amt)
            if c_amt <= 0.009:
                j += 1
            else:
                creditors[j] = (c_email, c_amt)

        # Replace debts
        self.debts = {k: v for k, v in simplified.items() if v > 0.009}

    def summary_lines(self, users_by_email: Dict[str, User]) -> List[str]:
        out = []
        for (debtor, creditor), amt in sorted(self.debts.items()):
            d = users_by_email.get(debtor, User(debtor, debtor)).name
            c = users_by_email.get(creditor, User(creditor, creditor)).name
            out.append(f"{d} owes {c} ₹{amt:.2f}")
        if not out:
            out.append("No outstanding debts.")
        return out

# ================ Group ================

@dataclass
class Group:
    name: str
    members: List[User]
    expenses: List[Expense] = field(default_factory=list)
    debt_manager: DebtManager = field(default_factory=DebtManager)

    def add_expense(self, expense: Expense) -> None:
        # Validate participants subset of members
        emails = {u.email for u in self.members}
        for p in expense.participants + [expense.payer]:
            if p.email not in emails:
                raise ValueError(f"User {p} not in group '{self.name}'.")
        self.expenses.append(expense)
        self.debt_manager.update_debts_for_expense(expense)

    def view_debts(self) -> List[str]:
        return self.debt_manager.summary_lines({u.email: u for u in self.members})

    def settle_up(self, payer: User, receiver: User, amount: float) -> None:
        self.debt_manager.settle_up(payer, receiver, amount)

# ================ Persistence ================

class Storage:
    @staticmethod
    def save(filename: str, users: Dict[str, User], groups: Dict[str, Group]) -> None:
        def user_to_dict(u: User):
            return {"name": u.name, "email": u.email}

        data = {
            "users": [user_to_dict(u) for u in users.values()],
            "groups": []
        }
        for g in groups.values():
            grp = {
                "name": g.name,
                "members": [u.email for u in g.members],
                "expenses": [],
                "debts": [{"debtor": d, "creditor": c, "amount": amt}
                          for (d, c), amt in g.debt_manager.debts.items()]
            }
            for e in g.expenses:
                grp["expenses"].append({
                    "description": e.description,
                    "amount": e.amount,
                    "payer": e.payer.email,
                    "participants": [u.email for u in e.participants],
                    "strategy": e.strategy_name,
                    "details": e.details or {}
                })
            data["groups"].append(grp)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load(filename: str) -> Tuple[Dict[str, User], Dict[str, Group]]:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        users: Dict[str, User] = {u["email"]: User(u["name"], u["email"]) for u in data.get("users", [])}
        groups: Dict[str, Group] = {}
        for g in data.get("groups", []):
            members = [users[email] for email in g.get("members", []) if email in users]
            group = Group(g["name"], members)
            # Rebuild expenses
            for e in g.get("expenses", []):
                payer = users[e["payer"]]
                participants = [users[em] for em in e["participants"]]
                exp = Expense(
                    description=e["description"],
                    amount=float(e["amount"]),
                    payer=payer,
                    participants=participants,
                    strategy_name=e["strategy"],
                    details=e.get("details", {})
                )
                group.add_expense(exp)
            # Replace debts from file (trusted) and simplify once
            group.debt_manager.debts = {(d["debtor"], d["creditor"]): float(d["amount"]) for d in g.get("debts", [])}
            group.debt_manager.simplify_debts()
            groups[group.name] = group
        return users, groups

# ================ Application (CLI) ================

class SplitSmartApp:
    def __init__(self) -> None:
        self.users: Dict[str, User] = {}      # email -> User
        self.groups: Dict[str, Group] = {}    # name -> Group

    # ----- User & Group management -----
    def add_user(self, name: str, email: str) -> None:
        email = email.strip().lower()
        if email in self.users:
            print("User already exists.")
            return
        self.users[email] = User(name=name.strip(), email=email)
        print("User added successfully!")

    def create_group(self, name: str, member_emails: List[str]) -> None:
        name = name.strip()
        if name in self.groups:
            print("Group already exists.")
            return
        members = []
        for em in member_emails:
            em = em.strip().lower()
            if em not in self.users:
                print(f"User with email {em} does not exist; please add user first.")
                return
            members.append(self.users[em])
        self.groups[name] = Group(name=name, members=members)
        print("Group created successfully!")

    # ----- Expense handling -----
    def add_expense(self) -> None:
        group_name = input("Enter group name: ").strip()
        if group_name not in self.groups:
            print("Group not found.")
            return
        group = self.groups[group_name]

        description = input("Enter expense description: ").strip()
        try:
            amount = float(input("Enter total amount: ").strip())
        except ValueError:
            print("Invalid amount.")
            return

        payer_email = input("Who paid? (email): ").strip().lower()
        if payer_email not in self.users or self.users[payer_email] not in group.members:
            print("Payer must be an existing group member (by email).")
            return
        payer = self.users[payer_email]

        part_emails = input("Members involved (emails, comma separated; leave blank = all members): ").strip()
        if part_emails:
            participants = []
            for em in [e.strip().lower() for e in part_emails.split(",")]:
                if em not in self.users or self.users[em] not in group.members:
                    print(f"Participant {em} is not a member of the group.")
                    return
                participants.append(self.users[em])
        else:
            participants = list(group.members)

        split_type = input("Split type (equal / unequal / percent / shares): ").strip().lower()
        details = None
        if split_type == "unequal":
            print("Enter amounts per participant (email:amount), comma separated")
            raw = input("e.g., a@x.com:1200,b@y.com:800 : ").strip()
            pairs = [p.strip() for p in raw.split(",") if p.strip()]
            amts = {}
            for p in pairs:
                em, val = [x.strip() for x in p.split(":")]
                amts[em.lower()] = float(val)
            details = {"amounts": amts}
        elif split_type in ("percent", "percentage", "percents"):
            print("Enter percents per participant (email:percent), sum must be 100")
            raw = input("e.g., a@x.com:50,b@y.com:50 : ").strip()
            pairs = [p.strip() for p in raw.split(",") if p.strip()]
            pcts = {}
            for p in pairs:
                em, val = [x.strip() for x in p.split(":")]
                pcts[em.lower()] = float(val)
            details = {"percents": pcts}
        elif split_type in ("shares", "ratio"):
            print("Enter integer shares per participant (email:shares)")
            raw = input("e.g., a@x.com:3,b@y.com:1 : ").strip()
            pairs = [p.strip() for p in raw.split(",") if p.strip()]
            shares = {}
            for p in pairs:
                em, val = [x.strip() for x in p.split(":")]
                shares[em.lower()] = int(val)
            details = {"shares": shares}

        try:
            expense = Expense(description, amount, payer, participants, split_type, details)
            group.add_expense(expense)
            print("Expense recorded successfully!")
            self._print_debts(group)
        except Exception as e:
            print(f"Failed to add expense: {e}")

    def view_debts(self) -> None:
        group_name = input("Enter group name: ").strip()
        if group_name not in self.groups:
            print("Group not found.")
            return
        self._print_debts(self.groups[group_name])

    def _print_debts(self, group: Group) -> None:
        print("Current Debts:")
        for line in group.view_debts():
            print(line)

    def settle_up(self) -> None:
        group_name = input("Enter group name: ").strip()
        if group_name not in self.groups:
            print("Group not found.")
            return
        group = self.groups[group_name]
        payer_email = input("Payer email: ").strip().lower()
        receiver_email = input("Receiver email: ").strip().lower()
        amount = float(input("Amount: ").strip())
        if payer_email not in self.users or receiver_email not in self.users:
            print("Emails must be existing users.")
            return
        if self.users[payer_email] not in group.members or self.users[receiver_email] not in group.members:
            print("Both users must be group members.")
            return
        group.settle_up(self.users[payer_email], self.users[receiver_email], amount)
        print("Settlement recorded.")
        self._print_debts(group)

    # ----- Persistence -----
    def save_load(self) -> None:
        choice = input("Type 'save' or 'load': ").strip().lower()
        filename = input("Filename (e.g., data.json): ").strip()
        if choice == "save":
            Storage.save(filename, self.users, self.groups)
            print(f"Saved to {filename}")
        elif choice == "load":
            try:
                self.users, self.groups = Storage.load(filename)
                print(f"Loaded from {filename}")
            except Exception as e:
                print(f"Failed to load: {e}")
        else:
            print("Unknown choice.")

    # ----- Main Menu -----
    def run_menu(self) -> None:
        while True:
            print("\nSplitSmart Menu")
            print("1. Add User")
            print("2. Create Group")
            print("3. Add Expense")
            print("4. View Debts")
            print("5. Settle Up")
            print("6. Save / Load Data")
            print("7. Exit")
            choice = input("Enter choice: ").strip()
            if choice == "1":
                name = input("Enter user name: ").strip()
                email = input("Enter email: ").strip().lower()
                self.add_user(name, email)
            elif choice == "2":
                name = input("Enter group name: ").strip()
                members = [e.strip().lower() for e in input("Add member emails (comma separated): ").split(",")]
                self.create_group(name, members)
            elif choice == "3":
                self.add_expense()
            elif choice == "4":
                self.view_debts()
            elif choice == "5":
                self.settle_up()
            elif choice == "6":
                self.save_load()
            elif choice == "7":
                print("Goodbye!")
                break
            else:
                print("Invalid choice. Try again.")

# ================ Entry Point ================

def main(argv: Optional[List[str]] = None) -> None:
    app = SplitSmartApp()
    app.run_menu()

if __name__ == "__main__":
    main()
