from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip
import frappe
from frappe import _, msgprint
from frappe.utils import (
	add_days,
	cint,
	cstr,
	date_diff,
	flt,
	formatdate,
	get_first_day,
	getdate,
	money_in_words,
	rounded,
)
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import (
	process_loan_interest_accrual_for_term_loans,
)
from lending.loan_management.doctype.loan_repayment.loan_repayment import (
	calculate_amounts,
	create_repayment_entry,
)
from paie.override.loan_repayment import (
	create_repayment_entry2,
)
from hrms.payroll.doctype.payroll_period.payroll_period import (
	get_payroll_period,
	get_period_factor,
)
from collections import defaultdict

class CustomSalarySlip(SalarySlip):

	@property
	def remaining_sub_periods(self):
		if not hasattr(self, "_remaining_sub_periods"):
			self._remaining_sub_periods = get_period_factor(
				self.employee, self.start_date, self.end_date, self.payroll_frequency, self.payroll_period
			)[1]

		return self._remaining_sub_periods

	def check_existing(self):
			if not self.salary_slip_based_on_timesheet:
				cond = ""
				if self.payroll_entry:
					cond += "and payroll_entry = '{0}'".format(self.payroll_entry)
				ret_exist = frappe.db.sql(
					"""select name from `tabSalary Slip`
							where start_date = %s and end_date = %s and docstatus != 2
							and employee = %s and name != %s and salary_type = %s {0}""".format(
						cond
					),
					(self.start_date, self.end_date, self.employee, self.name, self.salary_type),
				)
				if ret_exist:
					frappe.throw(
						_("Salary Slip of employee {0} already created for this period").format(self.employee)
					)
			else:
				for data in self.timesheets:
					if frappe.db.get_value("Timesheet", data.time_sheet, "status") == "Payrolled":
						frappe.throw(
							_("Salary Slip of employee {0} already created for time sheet {1}").format(
								self.employee, data.time_sheet
							)
						)

	@frappe.whitelist()
	def get_emp_and_working_day_details(self):
		"""First time, load all the components from salary structure"""
		if self.employee:
			self.set("earnings", [])
			self.set("deductions", [])

			if not self.salary_slip_based_on_timesheet:
				self.get_date_details()

			joining_date, relieving_date = frappe.get_cached_value(
				"Employee", self.employee, ("date_of_joining", "relieving_date")
			)

			self.validate_dates()

			# getin leave details
			self.get_working_days_details_2(joining_date, relieving_date)
			struct = ''
			if not self.salary_structure : 
				struct = self.check_sal_struct()
			else: 
				struct = self.salary_structure

			if struct:
				self._salary_structure_doc = frappe.get_doc("Salary Structure", struct)
				self.salary_slip_based_on_timesheet = (
					self._salary_structure_doc.salary_slip_based_on_timesheet or 0
				)
				self.set_time_sheet()
				self.pull_sal_struct()
				ps = frappe.db.get_value(
					"Payroll Settings", None, ["payroll_based_on", "consider_unmarked_attendance_as"], as_dict=1
				)
				return [ps.payroll_based_on, ps.consider_unmarked_attendance_as]

	def calculate_net_pay(self):
		if self.salary_structure:
			self.calculate_component_amounts("earnings")

		# get remaining numbers of sub-period (period for which one salary is processed)
		#if self.pay_period:
		#	self.remaining_sub_periods = get_period_factor(
		#		self.employee, self.start_date, self.end_date, self.payroll_frequency, self.payroll_period
		#	)[1]
		
		self.gross_pay = self.get_component_totals("earnings", depends_on_payment_days=1)
		self.base_gross_pay = flt(
			flt(self.gross_pay) * flt(self.exchange_rate), self.precision("base_gross_pay")
		)

		if self.salary_structure:
			self.calculate_component_amounts("deductions")

		if self.is_main_salary == 1: 
			self.set_loan_repayment()
		self.set_precision_for_component_amounts()
		self.set_net_pay()

	def get_loan_details(self):
		
		loan_details = frappe.get_all(
			"Loan",
			fields=["name", "interest_income_account", "loan_account", "loan_type", "is_term_loan", "exchange_rate"],
			filters={
				"applicant": self.employee,
				"docstatus": 1,
				"company": self.company,
				"repay_from_salary_slip": 1
			},
		)
		#frappe.msgprint("Loan details ",str(loan_details))
		if loan_details:
			for loan in loan_details:
				if loan.is_term_loan:
					process_loan_interest_accrual_for_term_loans(
						posting_date=self.posting_date, loan_product=loan.loan_product, loan=loan.name
					)

		return loan_details

	def set_loan_repayment(self):
		self.total_loan_repayment = 0
		self.total_interest_amount = 0
		self.total_principal_amount = 0
		self.total_loan_repayment_foreign_currency = 0
		self.total_interest_amount_foreign_currency = 0
		self.total_principal_amount_foreign_currency = 0

		if not self.get("loans"):
			for loan in self.get_loan_details():

				amounts = calculate_amounts(loan.name, self.posting_date, "Regular Payment")
				#frappe.msgprint(str(amounts))
				if amounts["interest_amount"] or amounts["payable_principal_amount"]:
					self.append(
						"loans",
						{
							"loan": loan.name,
							"total_payment": amounts["interest_amount"] + amounts["payable_principal_amount"],
							"interest_amount": amounts["interest_amount"],
							"principal_amount": amounts["payable_principal_amount"],
							"loan_account": loan.loan_account,
							"interest_income_account": loan.interest_income_account,
							"total_payment_foreign_currency": amounts["interest_amount"] + amounts["payable_principal_amount"] / loan.exchange_rate,
							"interest_amount_foreign_currency": amounts["interest_amount"] / loan.exchange_rate,
							"principal_amount_foreign_currency": amounts["payable_principal_amount"] / loan.exchange_rate,
							"loan_exchange_rate":loan.exchange_rate,
							"loan_type": loan.loan_type,
						},
					)

		for payment in self.get("loans"):
			
			amounts = calculate_amounts(payment.loan, self.posting_date, "Regular Payment")
			total_amount = amounts["interest_amount"] + amounts["payable_principal_amount"]
			if payment.total_payment > total_amount:
				frappe.throw(
					_(
						"""Row {0}: Paid amount {1} is greater than pending accrued amount {2} against loan {3}"""
					).format(
						payment.idx,
						frappe.bold(payment.total_payment),
						frappe.bold(total_amount),
						frappe.bold(payment.loan),
					)
				)

			self.total_interest_amount += payment.interest_amount
			self.total_principal_amount += payment.principal_amount

			self.total_loan_repayment += payment.total_payment
			
			self.total_interest_amount_foreign_currency += payment.interest_amount_foreign_currency
			self.total_principal_amount_foreign_currency += payment.principal_amount_foreign_currency

			self.total_loan_repayment_foreign_currency += payment.total_payment_foreign_currency
			
	@frappe.whitelist()
	def set_totals(self):
		self.gross_pay = 0.0
		if self.salary_slip_based_on_timesheet == 1:
			self.calculate_total_for_salary_slip_based_on_timesheet()
		else:
			self.total_deduction = 0.0
			if hasattr(self, "earnings"):
				for earning in self.earnings:
					self.gross_pay += flt(earning.amount, earning.precision("amount"))
			if hasattr(self, "deductions"):
				for deduction in self.deductions:
					self.total_deduction += flt(deduction.amount, deduction.precision("amount"))
			#frappe.msgprint(str(self.total_loan_repayment_foreign_currency))
			self.net_pay = flt(self.gross_pay) - flt(self.total_deduction) - flt(self.total_loan_repayment_foreign_currency)
		self.set_base_totals()

	def set_net_pay(self):
		self.total_deduction = self.get_component_totals("deductions")
		self.base_total_deduction = flt(
			flt(self.total_deduction) * flt(self.exchange_rate), self.precision("base_total_deduction")
		)
		self.net_pay = flt(self.gross_pay) - (flt(self.total_deduction) + flt(self.total_loan_repayment_foreign_currency))
		self.rounded_total = rounded(self.net_pay)
		self.base_net_pay = flt(
			flt(self.net_pay) * flt(self.exchange_rate), self.precision("base_net_pay")
		)
		self.base_rounded_total = flt(rounded(self.base_net_pay), self.precision("base_net_pay"))
		if self.hour_rate:
			self.base_hour_rate = flt(
				flt(self.hour_rate) * flt(self.exchange_rate), self.precision("base_hour_rate")
			)
		self.set_net_total_in_words()

	def calculate_lwp_or_ppl_based_on_leave_application(self, holidays, working_days_list, relieving_date):
		lwp = 0
		leave_type_lwp = []
		
		if isinstance(holidays, str):
			#holidays = "','".join(holidays)
			holidays = [h.strip("'") for h in holidays.split(",")]

		feries = holidays
		daily_wages_fraction_for_half_day = (
			flt(frappe.db.get_value("Payroll Settings", None, "daily_wages_fraction_for_half_day")) or 0.5
		)

		nb_working_days = len(working_days_list)
		for d in range(nb_working_days + len(feries)):
			date = add_days(cstr(getdate(self.start_date)), d)
			leave = get_lwp_or_ppl_for_date_2(date, self.employee, holidays)

			if leave:
				equivalent_lwp_count = 0
				is_half_day_leave = cint(leave[0].is_half_day)
				is_partially_paid_leave = cint(leave[0].is_ppl)
				fraction_of_daily_salary_per_leave = flt(leave[0].fraction_of_daily_salary_per_leave)

				equivalent_lwp_count = (1 - daily_wages_fraction_for_half_day) if is_half_day_leave else 1

				if is_partially_paid_leave:
					equivalent_lwp_count *= (fraction_of_daily_salary_per_leave if fraction_of_daily_salary_per_leave else 1)

				lwp += equivalent_lwp_count

				leave_type_lwp.append({
					"leave_type": leave[0].name,
					"jour": 1,
					"fraction": fraction_of_daily_salary_per_leave,
				})

		occurrence_counts = {}
		total_conge = 0

		for entry in leave_type_lwp:
			total_conge = total_conge + 1
			leave_type = entry['leave_type']
			if leave_type in occurrence_counts:
				occurrence_counts[leave_type] += 1
			else:
				occurrence_counts[leave_type] = 1

			#frappe.msgprint(str(entry['leave_type']))

		self.conge_pris = []
		for leave_type, count in occurrence_counts.items():
			self.append('conge_pris',{
				'leave_type': leave_type,
				'jour': count,
			})
			#self.append('conge_pris',{
			#		'leave_type': leave_type,
			#		'jour': count,
			#		#'fraction': fraction,
			#	}
			#)

		self.total_leaves = lwp
		
		return lwp


	#def calculate_lwp_or_ppl_based_on_leave_application(self, holidays, working_days, relieving_date):
	#	lwp = 0
	#	holidays = "','".join(holidays)
	#	feries = holidays.split(',')
	#	nb = len(feries)
	#	daily_wages_fraction_for_half_day = (
	#		flt(frappe.db.get_value("Payroll Settings", None, "daily_wages_fraction_for_half_day")) or 0.5
	#	)

	#	#frappe.msgprint(str(working_days))
	#	for d in range(len(working_days) + nb):
	#		date = add_days(cstr(getdate(self.start_date)), d)
	#		leave = get_lwp_or_ppl_for_date(date, self.employee, holidays)
	#		#frappe.msgprint(str(d) + " | " + str(date))
	#		#if relieving_date and d > relieving_date:
	#		#	continue
	#		if leave:
	#			equivalent_lwp_count = 0
	#			is_half_day_leave = cint(leave[0].is_half_day)
	#			is_partially_paid_leave = cint(leave[0].is_ppl)
	#			fraction_of_daily_salary_per_leave = flt(leave[0].fraction_of_daily_salary_per_leave)
	#
	#			equivalent_lwp_count = (1 - daily_wages_fraction_for_half_day) if is_half_day_leave else 1

	#			if is_partially_paid_leave:
	#				equivalent_lwp_count *= (
	#					fraction_of_daily_salary_per_leave if fraction_of_daily_salary_per_leave else 1
	#				)

	#			lwp += equivalent_lwp_count
	#			#frappe.msgprint(str(lwp))
	#	return lwp

	def make_loan_repayment_entry(self):
		payroll_payable_account = get_payroll_payable_account(self.company, self.payroll_entry)
		for loan in self.loans:
			if loan.total_payment:
				emp = frappe.get_doc("Employee",self.employee)
				repayment_entry = create_repayment_entry2(
					loan.loan,
					self.employee,
					self.company,
					self.posting_date,
					loan.loan_type,
					"Regular Payment",
					loan.interest_amount,
					loan.principal_amount,
					loan.total_payment,
					emp.payroll_cost_center,
					emp.branch,
					payroll_payable_account=payroll_payable_account,
				)

				repayment_entry.save()
				repayment_entry.submit()

				frappe.db.set_value(
					"Salary Slip Loan", loan.name, "loan_repayment_entry", repayment_entry.name
				)

	def calculate_lwp_or_ppl_based_on_leave_application_2(
		self, holidays, working_days_list, relieving_date
	):
		lwp = 0
		leave_type_lwp = []
		type = ""
		holidays = "','".join(holidays)
		feries = holidays.split(',')
		nb = len(feries)
		daily_wages_fraction_for_half_day = (
			flt(frappe.db.get_value("Payroll Settings", None, "daily_wages_fraction_for_half_day")) or 0.5
		)
		#frappe.msgprint(str(nb))
		#frappe.msgprint(str(len(working_days_list)))
		#frappe.msgprint(str(holidays))

		nb_working_days = len(working_days_list) 
		for d in range(nb_working_days):
			date = add_days(cstr(getdate(self.start_date)), d)
			leave = get_lwp_or_ppl_for_date_2(date, self.employee, holidays)

			if leave:
				equivalent_lwp_count = 0
				is_half_day_leave = cint(leave[0].is_half_day)
				is_partially_paid_leave = cint(leave[0].is_ppl)
				fraction_of_daily_salary_per_leave = flt(leave[0].fraction_of_daily_salary_per_leave)

				leave_type_lwp.append({"leave_type": leave[0].name,"jour":1, "fraction":fraction_of_daily_salary_per_leave,})
		
		# Create a dictionary to count occurrences by 'leave_type'
		occurrence_counts = {}
		total_conge = 0

		for entry in leave_type_lwp:
			total_conge = total_conge + 1
			leave_type = entry['leave_type']
			#fraction = entry['fraction']
			#key = (leave_type, fraction)  # Create a tuple as the key
			if leave_type in occurrence_counts:
				occurrence_counts[leave_type] += 1
			else:
				occurrence_counts[leave_type] = 1
		
		#frappe.msgprint(str(occurrence_counts))
		for leave_type, count in occurrence_counts.items():
			self.append('conge_pris',{
					'leave_type': leave_type,
					'jour': count,
					#'fraction': fraction,
				}
			)
		
		self.total_leaves = total_conge
		#return leave_type_lwp

	def get_working_days_details_2(
		self, joining_date=None, relieving_date=None, lwp=None, for_preview=0
	):
		payroll_based_on = frappe.db.get_value("Payroll Settings", None, "payroll_based_on")
		include_holidays_in_total_working_days = frappe.db.get_single_value(
			"Payroll Settings", "include_holidays_in_total_working_days"
		)

		if not (joining_date and relieving_date):
			#joining_date, relieving_date = self.get_joining_and_relieving_dates()
			joining_date, relieving_date = frappe.get_cached_value(
				"Employee", self.employee, ("date_of_joining", "relieving_date")
			)

		working_days = date_diff(self.end_date, self.start_date) + 1
		if for_preview:
			self.total_working_days = working_days
			self.payment_days = working_days
			return

		holidays = self.get_holidays_for_employee(self.start_date, self.end_date)
		working_days_list = [
			add_days(getdate(self.start_date), days=day) for day in range(0, working_days)
		]

		if not cint(include_holidays_in_total_working_days):
			working_days_list = [i for i in working_days_list if str(i) not in holidays]

			working_days -= len(holidays)
			if working_days < 0:
				frappe.throw(_("There are more holidays than working days this month."))

		if not payroll_based_on:
			frappe.throw(_("Please set Payroll based on in Payroll settings"))

		if payroll_based_on == "Attendance":
			actual_lwp, absent = self.calculate_lwp_ppl_and_absent_days_based_on_attendance(
				holidays, relieving_date
			)
			self.absent_days = absent
		else:
			actual_lwp = self.calculate_lwp_or_ppl_based_on_leave_application(
				holidays, working_days_list, relieving_date
			)

			#self.calculate_lwp_or_ppl_based_on_leave_application_2(
			#	holidays, working_days_list, relieving_date
			#)

		if not lwp:
			lwp = actual_lwp
		elif lwp != actual_lwp:
			frappe.msgprint(
				_("Leave Without Pay does not match with approved {} records").format(payroll_based_on)
			)

		self.leave_without_pay = lwp
		self.total_working_days = working_days

		payment_days = self.get_payment_days(
			include_holidays_in_total_working_days
		)

		if flt(payment_days) > flt(lwp):
			self.payment_days = flt(payment_days) - flt(lwp)

			if payroll_based_on == "Attendance":
				self.payment_days -= flt(absent)

			consider_unmarked_attendance_as = (
				frappe.db.get_value("Payroll Settings", None, "consider_unmarked_attendance_as") or "Present"
			)

			if payroll_based_on == "Attendance" and consider_unmarked_attendance_as == "Absent":
				unmarked_days = self.get_unmarked_days(include_holidays_in_total_working_days)
				self.absent_days += unmarked_days  # will be treated as absent
				self.payment_days -= unmarked_days
		else:
			self.payment_days = 0


def get_payroll_payable_account(company, payroll_entry):
	if payroll_entry:
		payroll_payable_account = frappe.db.get_value(
			"Payroll Entry", payroll_entry, "payroll_payable_account"
		)
	else:
		payroll_payable_account = frappe.db.get_value(
			"Company", company, "default_payroll_payable_account"
		)

	return payroll_payable_account


def get_lwp_or_ppl_for_date_2(date, employee, holidays):
	LeaveApplication = frappe.qb.DocType("Leave Application")
	LeaveType = frappe.qb.DocType("Leave Type")

	is_half_day = (
		frappe.qb.terms.Case()
		.when(
			(
				(LeaveApplication.half_day_date == date)
				| (LeaveApplication.from_date == LeaveApplication.to_date)
			),
			LeaveApplication.half_day,
		)
		.else_(0)
	).as_("is_half_day")

	query = (
		frappe.qb.from_(LeaveApplication)
		.inner_join(LeaveType)
		.on((LeaveType.name == LeaveApplication.leave_type))
		.select(
			LeaveType.name,
			LeaveType.is_ppl,
			LeaveType.fraction_of_daily_salary_per_leave,
			(is_half_day),
		)
		.where(
			(((LeaveType.is_lwp == 1) | (LeaveType.is_ppl == 1)))
			& (LeaveApplication.docstatus == 1)
			& (LeaveApplication.status == "Approved")
			& (LeaveApplication.employee == employee)
			& ((LeaveApplication.salary_slip.isnull()) | (LeaveApplication.salary_slip == ""))
			& ((LeaveApplication.from_date <= date) & (date <= LeaveApplication.to_date))
		)
		#.order_by(LeaveType.name)
	)

	# if it's a holiday only include if leave type has "include holiday" enabled
	if date in holidays:
		query = query.where((LeaveType.include_holiday == "1"))

	return query.run(as_dict=True)




