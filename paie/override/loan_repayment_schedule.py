import frappe
from lending.loan_management.doctype.loan_repayment_schedule.loan_repayment_schedule import LoanRepaymentSchedule

class CustomLoanRepaymentSchedule(LoanRepaymentSchedule):

    def add_repayment_schedule_row(
        self, payment_date, principal_amount, interest_amount, total_payment, balance_loan_amount, days
    ):
        self.append(
            "repayment_schedule",
            {
                "number_of_days": days,
                "payment_date": payment_date,
                "principal_amount": principal_amount,
                "interest_amount": interest_amount,
                "total_payment": total_payment,
                "balance_loan_amount": balance_loan_amount,
                "principal_amount_foreign_currency": principal_amount / self.exchange_rate,
                "interest_amount_foreign_currency": interest_amount / self.exchange_rate,
                "total_payment_foreign_currency": total_payment / self.exchange_rate,
                "balance_loan_amount_foreign_currency": balance_loan_amount / self.exchange_rate,
            },
        )