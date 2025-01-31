from hrms.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry
import frappe
from frappe import _

import json

from dateutil.relativedelta import relativedelta


from frappe.desk.reportview import get_filters_cond, get_match_cond
from frappe.model.document import Document
from frappe.query_builder.functions import Coalesce
from frappe.utils import (
	DATE_FORMAT,
	add_days,
	add_to_date,
	cint,
	comma_and,
	date_diff,
	flt,
	get_link_to_form,
	getdate,
)

import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)
from erpnext.accounts.utils import get_fiscal_year
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from hrms.hr.utils import get_holiday_dates_for_employee
from paie.override.journal_entry import CustomJournalEntry
from lending.loan_management.doctype.process_loan_interest_accrual.process_loan_interest_accrual import process_loan_interest_accrual_for_term_loans

class CustomPayrollEntry(PayrollEntry):
    @frappe.whitelist()
    def fill_employee_details(self):
        filters = self.make_filters()
        employees = self.get_emp_list()
        self.set("employees", [])

        if not employees:
            error_msg = _(
                "No employees found for the mentioned criteria:<br>Company: {0}<br> Currency: {1}<br>Payroll Payable Account: {2}"
            ).format(
                frappe.bold(self.company),
                frappe.bold(self.currency),
                frappe.bold(self.payroll_payable_account),
            )
            if self.branch:
                error_msg += "<br>" + _("Branch: {0}").format(frappe.bold(self.branch))
            if self.department:
                error_msg += "<br>" + _("Department: {0}").format(frappe.bold(self.department))
            if self.designation:
                error_msg += "<br>" + _("Designation: {0}").format(frappe.bold(self.designation))
            if self.start_date:
                error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
            if self.end_date:
                error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
            frappe.throw(error_msg, title=_("No employees found"))

        self.set("employees", employees)
        self.number_of_employees = len(self.employees)
        self.update_employees_with_withheld_salaries()

        return self.get_employees_with_unmarked_attendance()

    def make_filters(self):
        filters = frappe._dict(
            company=self.company,
            branch=self.branch,
            department=self.department,
            designation=self.designation,
            grade=self.grade,
            currency=self.currency,
            start_date=self.start_date,
            end_date=self.end_date,
            payroll_payable_account=self.payroll_payable_account,
            salary_slip_based_on_timesheet=self.salary_slip_based_on_timesheet,
            employment_type=self.employment_type,
        )

        if not self.salary_slip_based_on_timesheet:
            filters.update(dict(payroll_frequency=self.payroll_frequency))

        return filters

    def before_save(self):
        if frappe.db.get_single_value("Custom Paie Settings", "automatic_seniority"):
            args = {
                'doctype': 'Anciennete',
                'company': self.company,
                'payroll_period': self.payroll_period,
                'posting_date': self.posting_date
            }
            if self.branch :
                args.update({ "branch": self.branch })
            if self.employment_type :
                args.update({ "employment_type": self.employment_type })

            doc = frappe.get_doc(args)
            if doc:
                doc.insert()
                doc.submit()

    def calcul_absence(self,emp):
        holiday = get_holiday_dates_for_employee(emp, self.start_date, self.end_date)
        attendance = frappe.db.count('Attendance', filters=[
                        ['employee', '=', emp],
                        ['attendance_date', 'between', [self.start_date, self.end_date]],
                        ['status', 'IN', ['Absent', 'On Leave']]
                    ])
        return attendance - len(holiday)

    def calcul_conge_annuel(self,emp, from_date, to_date):
        conge = frappe.db.sql_list(
            """
            SELECT a.total_leave_days
            FROM `tabLeave Application` a INNER JOIN `tabLeave Type` t ON a.leave_type = t.name
            WHERE a.employee = %s AND a.from_date BETWEEN %s AND %s AND a.status = 'Approved' AND is_circumstance = 0
            LIMIT 1
            """ , (emp, from_date, to_date),
        )
        #frappe.msgprint(str(conge or 0))
        if len(conge) == 0 :
            return 0
        return conge[0]

    def get_existing_salary_slips(self,employees, args):
        return frappe.db.sql_list(
            """
            select distinct employee, salary_type 
            from `tabSalary Slip`
            where docstatus!= 2 and company = %s
                and start_date >= %s and end_date <= %s
                and employee in (%s)
        """
            % ("%s", "%s", "%s", ", ".join(["%s"] * len(employees))),
            [args.company, args.start_date, args.end_date] + employees,
        )


    def create_salary_slips_for_employees(self,employees, args, publish_progress=True):
        try:
            process_loan_interest_accrual_for_term_loans()
            liste = frappe.db.get_list("Loan","name",{"status": "Partially Disbursed"})
            for i in liste:
                doc = frappe.get_doc({
                    'doctype': 'Loan Disbursement',
                    'disbursement_date': self.end_date,
                    'disbursed_amount': 0,
                    'against_loan': i.name,
                })
                doc.submit()
                    
            payroll_entry = frappe.get_doc("Payroll Entry", args.payroll_entry)
            salary_slips_exist_for = self.get_existing_salary_slips(employees, args)
            jour_ouvrable = frappe.db.get_single_value("Custom Paie Settings", "jour_ouvrable")
            multiple_salary_in_period = frappe.db.get_single_value("Custom Paie Settings", "multiple_salary_in_period")
            count = 0

            #frappe.msgprint(str(salary_slips_exist_for))
            
            
            for emp in employees:
                employee = frappe.get_doc('Employee', emp)
                if employee.vacation == 1 :
                    continue # Skip to the next iteration

                leaves = self.calcul_conge_annuel(emp, self.start_date, self.end_date)
                #employee.absence = self.calcul_absence(emp)
                employee.jour_conge = leaves
                #employee.conge_period = leaves
                employee.save()

                salary_types = frappe.db.get_list(doctype="Salary Structure Assignment", fields=["salary_type", "salary_structure"], 
                    filters={"eventual": 0, "employee": emp, "docstatus": 1})

                #Prime de fin d'année
                bonus_in_separate_slip = frappe.db.get_single_value('Custom Paie Settings', 'bonus_in_separate_slip')
                if bonus_in_separate_slip == 1:
                    if getdate(self.end_date).month == 12 :
                        leaves_struc = frappe.db.get_list(doctype="Salary Structure Assignment", fields=["salary_type", "salary_structure"], 
                        filters={"eventual": 1, "employee": emp, "docstatus": 1, 'event_name': 'Prime annuelle'})
                        if len(leaves_struc) > 0: 
                            salary_types = salary_types + leaves_struc
                
                if leaves > 0 :
                    leaves_struc = frappe.db.get_list(doctype="Salary Structure Assignment", fields=["salary_type", "salary_structure"], 
                    filters={"eventual": 1, "employee": emp, "docstatus": 1, 'event_name': 'Congé Annuel'})
                    if len(leaves_struc) > 0: 
                        salary_types = salary_types + leaves_struc

                if employee.retirement == 1 : 
                    ret_struc = frappe.db.get_list(doctype="Salary Structure Assignment", fields=["salary_type", "salary_structure"], 
                    filters={"eventual": 1, "employee": emp, "docstatus": 1, 'event_name': 'Retraite'})
                    if len(ret_struc) > 0: 
                        salary_types = salary_types + ret_struc

                for t in salary_types:
                    #frappe.msgprint(str( not frappe.db.exists("Salary Slip", {"employee": emp, "salary_type": t.salary_type, "payroll_period": self.payroll_period})))
                    #cat_details = frappe.get_doc("Employee Category Details", employee.employee_category_details)
                    attendances = frappe.db.sql(
                        """
                            SELECT l.*
                            FROM `tabAttendance list` a INNER JOIN `tabAttendance Line` l ON a.name = l.parent
                            WHERE a.pay_period = '%s' AND employee = '%s' AND a.docstatus = 1  
                        """ % (payroll_entry.payroll_period,emp), as_dict = 1
                    )
                    if multiple_salary_in_period :
                        exist = frappe.db.exists("Salary Slip", {"employee": emp, "salary_type": t.salary_type, "pay_period": self.payroll_period, "start_date": ["<=", self.start_date], "end_date": [">=", self.start_date]})
                    else:
                        exist = frappe.db.exists("Salary Slip", {"employee": emp, "salary_type": t.salary_type, "pay_period": self.payroll_period})
                    if not exist :
                        args.update({
                            "doctype": "Salary Slip", 
                            "employee": emp, 
                            "salary_type": t.salary_type, 
                            "salary_structure": t.salary_structure, 
                            "is_main_salary": t.is_main_salary,

                            "employee_category_details": employee.employee_category_details, 
                            "anciennete": employee.anciennete,
                            
                            #"present_days": employee.present_days, 
                            #"hours_30": employee.hours_30, 
                            #"night_hours": employee.night_hours, 
                            #"sunday_hours": employee.sunday_hours, 
                            #"hours_60": employee.hours_60,
                            #"absence": employee.absence, 

                            "present_days": (jour_ouvrable - attendances[0].absence) if len(attendances) > 0 else jour_ouvrable, 
                            "hours_30": attendances[0].hours_30 if len(attendances) > 0 else 0, 
                            "night_hours": attendances[0].night_hours if len(attendances) > 0 else 0, 
                            "sunday_hours": attendances[0].sunday_hours if len(attendances) > 0 else 0, 
                            "hours_60": attendances[0].hours_60 if len(attendances) > 0 else 0,
                            "absence": attendances[0].absence if len(attendances) > 0 else 0, 

                            "child": employee.child, 
                            "dependent": employee.dependent
                        })
                        frappe.get_doc(args).insert()
                        
                        #frappe.msgprint(str(args))

                        count += 1
                        if publish_progress:
                            frappe.publish_progress(
                                count * 100 / len(set(employees) - set(salary_slips_exist_for)),
                                title=_("Creating Salary Slips..."),
                            )

            payroll_entry.db_set({"status": "Submitted", "salary_slips_created": 1, "error_message": ""})

            if salary_slips_exist_for:
                frappe.msgprint(
                    _(
                        "Salary Slips already exist for employees {}, and will not be processed by this payroll."
                    ).format(frappe.bold(", ".join(emp for emp in salary_slips_exist_for))),
                    title=_("Message"),
                    indicator="orange",
                )
            
        except Exception as e:
            frappe.db.rollback()
            self.log_payroll_failure("creation", payroll_entry, e)

        finally:
            frappe.db.commit()  # nosemgrep
            frappe.publish_realtime("completed_salary_slip_creation")


    @frappe.whitelist()
    def create_salary_slips(self):
        """
        Creates salary slip for selected employees if already not created
        """
        self.check_permission("write")
        employees = [emp.employee for emp in self.employees]
        if employees:
            args = frappe._dict(
                {
                    "salary_slip_based_on_timesheet": self.salary_slip_based_on_timesheet,
                    "payroll_frequency": self.payroll_frequency,
                    "start_date": self.start_date,
                    "end_date": self.end_date,
                    "company": self.company,
                    "posting_date": self.posting_date,
                    "deduct_tax_for_unclaimed_employee_benefits": self.deduct_tax_for_unclaimed_employee_benefits,
                    "deduct_tax_for_unsubmitted_tax_exemption_proof": self.deduct_tax_for_unsubmitted_tax_exemption_proof,
                    "payroll_entry": self.name,
                    "exchange_rate": self.exchange_rate,
                    "currency": self.currency,
                    "eventual": self.eventual,
                    "pay_period": self.payroll_period
                }
            )
            if len(employees) > 30 or frappe.flags.enqueue_payroll_entry:
                self.db_set("status", "Queued")
                frappe.enqueue(
                    self.create_salary_slips_for_employees,
                    timeout=1800,
                    employees=employees,
                    args=args,
                    publish_progress=True,
                )
                frappe.msgprint(
                    _("Salary Slip creation is queued. It may take a few minutes"),
                    alert=True,
                    indicator="blue",
                )
            else:
                self.create_salary_slips_for_employees(employees, args, publish_progress=False)
                # since this method is called via frm.call this doc needs to be updated manually
                self.reload()

    def log_payroll_failure(self,process, payroll_entry, error):
        error_log = frappe.log_error(
            title=_("Salary Slip {0} failed for Payroll Entry {1}").format(process, payroll_entry.name)
        )
        message_log = frappe.message_log.pop() if frappe.message_log else str(error)

        try:
            error_message = json.loads(message_log).get("message")
        except Exception:
            error_message = message_log

        error_message += "\n" + _("Check Error Log {0} for more details.").format(
            get_link_to_form("Error Log", error_log.name)
        )

        payroll_entry.db_set({"error_message": error_message, "status": "Failed"})

    def make_accrual_jv_entry(self, submitted_salary_slips=None):
        self.check_permission("write")
        earnings = self.get_salary_component_total(component_type="earnings") or {}
        deductions = self.get_salary_component_total(component_type="deductions") or {}
        payroll_payable_account = self.payroll_payable_account
        jv_name = ""
        precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")

        if earnings or deductions:
            journal_entry = frappe.new_doc("Journal Entry")
            journal_entry.voucher_type = "Journal Entry"
            journal_entry.user_remark = _("Accrual Journal Entry for salaries from {0} to {1}").format(
                self.start_date, self.end_date
            )
            journal_entry.company = self.company
            journal_entry.posting_date = self.posting_date
            accounting_dimensions = get_accounting_dimensions() or []

            accounts = []
            currencies = []
            payable_amount = 0
            payable_amt2 = 0
            multi_currency = 0
            company_currency = erpnext.get_company_currency(self.company)

            # Earnings
            for acc_cc, amount in earnings.items():
                exchange_rate, amt = self.get_amount_and_exchange_rate_for_journal_entry(
                    acc_cc[0], amount, company_currency, currencies
                )
                payable_amount += flt(amount, precision)
                payable_amt2 += flt(amt, precision)
                accounts.append(
                    self.update_accounting_dimensions(
                        {
                            "account": acc_cc[0],
                            "debit_in_account_currency": flt(amt, precision),
                            "exchange_rate": flt(exchange_rate),
                            "cost_center": acc_cc[1] or self.cost_center,
                            "project": self.project,
                        },
                        accounting_dimensions,
                    )
                )

            # Deductions
            for acc_cc, amount in deductions.items():
                exchange_rate, amt = self.get_amount_and_exchange_rate_for_journal_entry(
                    acc_cc[0], amount, company_currency, currencies
                )
                payable_amount -= flt(amount, precision)
                payable_amt2 -= flt(amt, precision)
                accounts.append(
                    self.update_accounting_dimensions(
                        {
                            "account": acc_cc[0],
                            "credit_in_account_currency": flt(amt, precision),
                            "exchange_rate": flt(exchange_rate),
                            "cost_center": acc_cc[1] or self.cost_center,
                            "project": self.project,
                        },
                        accounting_dimensions,
                    )
                )

            # Payable amount
            exchange_rate, payable_amt = self.get_amount_and_exchange_rate_for_journal_entry(
                payroll_payable_account, payable_amount, company_currency, currencies
            )
            accounts.append(
                self.update_accounting_dimensions(
                    {
                        "account": payroll_payable_account,
                        "credit_in_account_currency": flt(payable_amt, precision),
                        "exchange_rate": flt(exchange_rate),
                        "cost_center": self.cost_center,
                    },
                    accounting_dimensions,
                )
            )
            if flt(payable_amt2 - payable_amt, precision) != 0 :
                #frappe.msgprint(str(payable_amt - payable_amt2))
                round_off_account = frappe.get_value("Company", self.company,"round_off_account")
                accounts.append(
                    self.update_accounting_dimensions(
                        {
                            "account": round_off_account, #"67600200 - Round Off - MCO",
                            "credit_in_account_currency": flt(payable_amt2 - payable_amt, precision),
                            "exchange_rate": flt(exchange_rate),
                            "cost_center": self.cost_center,
                        },
                        accounting_dimensions,
                    )
                )
            frappe.msgprint(str(payroll_payable_account))


            journal_entry.set("accounts", accounts)
            if len(currencies) > 1:
                multi_currency = 1
            journal_entry.multi_currency = multi_currency
            journal_entry.title = payroll_payable_account
            journal_entry.save()

            try:
                journal_entry.submit()
                jv_name = journal_entry.name
                self.update_salary_slip_status(jv_name=jv_name)
            except Exception as e:
                if type(e) in (str, list, tuple):
                    frappe.msgprint(e)
                raise
                
        return jv_name

    def update_salary_slip_status(self, jv_name=None):
        ss_list = self.get_sal_slip_list(ss_status=1)
        for ss in ss_list:
            ss_obj = frappe.get_doc("Salary Slip", ss[0])
            frappe.db.set_value("Salary Slip", ss_obj.name, "journal_entry", jv_name)

            
    def get_emp_list(self):
        """
        Returns list of active employees based on selected criteria
        and for which salary structure exists
        """
        #self.check_mandatory()
        filters = self.make_filters()
        cond = self.get_filter_condition2(filters)
        cond += self.get_joining_relieving_condition2(self.start_date, self.end_date)

        condition = ""
        if self.payroll_frequency:
            condition = """and payroll_frequency = '%(payroll_frequency)s'""" % {
                "payroll_frequency": self.payroll_frequency
            }

        sal_struct = self.get_sal_struct2(
            self.company, self.currency, self.salary_slip_based_on_timesheet, condition
        )
        if sal_struct:
            cond += "and t2.salary_structure IN %(sal_struct)s "
            cond += "and t2.payroll_payable_account = %(payroll_payable_account)s "
            cond += "and %(from_date)s >= t2.from_date"

            emp_list = self.get_emp_list2(sal_struct, cond, self.end_date, self.payroll_payable_account)
            emp_list = self.remove_payrolled_employees2(emp_list, self.start_date, self.end_date)
            return emp_list
    
    def make_filters(self):
        filters = frappe._dict()
        filters["company"] = self.company
        filters["branch"] = self.branch
        filters["department"] = self.department
        filters["designation"] = self.designation
        filters["employment_type"] = self.employment_type

        return filters


    def get_filter_condition2(self, filters):
        cond = ""
        for f in ["company", "branch", "department", "designation", "employment_type"]:
            if filters.get(f):
                cond += " and t1." + f + " = " + frappe.db.escape(filters.get(f))

        return cond

    def get_joining_relieving_condition2(self, start_date, end_date):
        cond = """
            and ifnull(t1.date_of_joining, '1900-01-01') <= '%(end_date)s'
            and ifnull(t1.relieving_date, '2199-12-31') >= '%(start_date)s'
        """ % {
            "start_date": start_date,
            "end_date": end_date,
        }
        return cond

    def get_sal_struct2(self, company: str, currency: str, salary_slip_based_on_timesheet: int, condition: str ):
        return frappe.db.sql_list(
            """
            select
                name from `tabSalary Structure`
            where
                docstatus = 1 and
                is_active = 'Yes'
                and company = %(company)s
                and currency = %(currency)s and
                ifnull(salary_slip_based_on_timesheet,0) = %(salary_slip_based_on_timesheet)s
                {condition}""".format(
                condition=condition
            ),
            {
                "company": company,
                "currency": currency,
                "salary_slip_based_on_timesheet": salary_slip_based_on_timesheet,
            },
        )

    def get_emp_list2(self, sal_struct, cond, end_date, payroll_payable_account):
        return frappe.db.sql(
            """
                select
                    distinct t1.name as employee, t1.employee_name, t1.department, t1.designation
                from
                    `tabEmployee` t1, `tabSalary Structure Assignment` t2
                where
                    t1.name = t2.employee
                    and t2.docstatus = 1
                    and t1.status != 'Inactive'
                    and t1.vacation = 0
            %s order by t2.from_date desc
            """
            % cond,
            {
                "sal_struct": tuple(sal_struct),
                "from_date": end_date,
                "payroll_payable_account": payroll_payable_account,
            },
            as_dict=True,
	    )

    def remove_payrolled_employees2(self, emp_list, start_date, end_date):
        new_emp_list = []
        for employee_details in emp_list:
            if not frappe.db.exists(
                "Salary Slip",
                {
                    "employee": employee_details.employee,
                    "start_date": start_date,
                    "end_date": end_date,
                    "docstatus": 1,
                },
            ):
                new_emp_list.append(employee_details)

        return new_emp_list

