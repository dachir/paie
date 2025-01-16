import json
import math

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_last_day, getdate, now_datetime, nowdate
from lending.loan_management.doctype.loan.loan import Loan
from lending.loan_management.doctype.loan_repayment_schedule.loan_repayment_schedule import add_single_month

import erpnext
from erpnext.accounts.doctype.journal_entry.journal_entry import get_payment_entry
from erpnext.controllers.accounts_controller import AccountsController
from lending.loan_management.doctype.loan_repayment.loan_repayment import calculate_amounts
from lending.loan_management.doctype.loan_security_unpledge.loan_security_unpledge import (
	get_pledged_security_qty,
)


class CustomLoan(Loan):
	def validate(self):
		self.set_loan_amount()
		self.set_monthly_repayment_amount() #need to check this required or not
		self.validate_loan_amount()
		self.set_missing_fields()
		self.validate_cost_center()
		self.validate_accounts()
		self.check_sanctioned_amount_limit()
		self.set_cyclic_date()  # Version 15 addition

		if self.is_term_loan and not self.is_new():
			self.update_draft_schedule()
        
		if not self.is_term_loan or (self.is_term_loan and not self.is_new()):
			self.calculate_totals()

		
	def after_insert(self):
		if self.is_term_loan:
			self.make_draft_schedule()
			self.calculate_totals(on_insert=True)

	def set_cyclic_date(self):  # New in version 15
		if self.repayment_schedule_type == "Monthly as per cycle date":
			cycle_day, min_days_bw_disbursement_first_repayment = frappe.db.get_value(
				"Loan Product",
				self.loan_product,
				["cyclic_day_of_the_month", "min_days_bw_disbursement_first_repayment"],
			)
				
	def validate_repayment_method(self):
		if self.repayment_method == "Repay Over Number of Periods" and not self.repayment_periods:
			frappe.throw(_("Please enter Repayment Periods"))

		if self.repayment_method == "Repay Fixed Amount per Period":
			if not self.repayment_amount:
				frappe.throw(_("Please enter repayment Amount"))
			if self.repayment_amount > self.loan_amount:
				frappe.throw(_("Monthly Repayment Amount cannot be greater than Loan Amount"))

	def make_draft_schedule(self): #Replaces make_payment_schedule
		if not self.repayment_start_date:
			frappe.throw(_("Repayment Start Date is mandatory for term loans"))

		self.repayment_schedule = []
		payment_date = self.repayment_start_date
		balance_amount = self.loan_amount
		while balance_amount > 0:
			interest_amount = flt(balance_amount * flt(self.rate_of_interest) / (12 * 100))
			principal_amount = self.monthly_repayment_amount - interest_amount
			balance_amount = flt(balance_amount + interest_amount - self.monthly_repayment_amount)
			if balance_amount < 0:
				principal_amount += balance_amount
				balance_amount = 0.0

			total_payment = principal_amount + interest_amount
			self.append(
				"repayment_schedule",
				{
					"payment_date": payment_date,
					"principal_amount": principal_amount,
					"interest_amount": interest_amount,
					"total_payment": total_payment,
					"balance_loan_amount": balance_amount,
				},
			)
			next_payment_date = add_single_month(payment_date)
			payment_date = next_payment_date

	def set_repayment_period(self):
		if self.repayment_method == "Repay Fixed Amount per Period":
			repayment_periods = len(self.repayment_schedule)

			self.repayment_periods = repayment_periods

	def calculate_totals(self, on_insert=False): #Add on_insert flag for new version
		self.total_payment = 0
		self.total_interest_payable = 0
		self.total_amount_paid = 0
		

		if self.is_term_loan:
			for data in self.repayment_schedule:
				self.total_payment += data.total_payment
				self.total_interest_payable += data.interest_amount
		else:
			self.total_payment = self.loan_amount

	def set_loan_amount(self):
		if self.loan_application and not self.loan_amount:
			self.loan_amount = frappe.db.get_value("Loan Application", self.loan_application, "loan_amount")
		
		if not self.loan_amount:
			self.loan_amount = self.loan_amount_in_loan_currency * self.exchange_rate
	
	def set_monthly_repayment_amount(self):
		if not self.monthly_repayment_amount:
			self.monthly_repayment_amount = self.monthly_repayment_amount_in_loan_currency * self.exchange_rate
