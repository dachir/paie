from . import __version__ as app_version

app_name = "paie"
app_title = "Paie Congo"
app_publisher = "Richard"
app_description = "Paie Congo"
app_email = "dodziamouzou@gmail.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/paie/css/paie.css"
# app_include_js = "/assets/paie/js/paie.js"

# include js, css files in header of web template
# web_include_css = "/assets/paie/css/paie.css"
# web_include_js = "/assets/paie/js/paie.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "paie/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "paie.utils.jinja_methods",
#	"filters": "paie.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "paie.install.before_install"
# after_install = "paie.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "paie.uninstall.before_uninstall"
# after_uninstall = "paie.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "paie.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
    "Salary Structure Assignment": "paie.override.salary_structure.CustomSalaryStructureAssignment",
    "Payroll Entry": "paie.override.payroll_entry.CustomPayrollEntry",
    "Salary Slip": "paie.override.salary_slip.CustomSalarySlip",
    #"Loan": "paie.override.loan.CustomLoan",
    #"Loan Repayment": "paie.override.loan_repayment.CustomLoanRepayment",
    "Loan Repayment Schedule": "paie.override.loan_repayment_schedule.CustomLoanRepaymentSchedule",
    "Journal Entry": "paie.override.journal_entry.CustomJournalEntry",
    "Leave Application": "paie.override.leave_application.CustomLeaveApplication",
    "Leave Allocation": "paie.override.leave_allocation.CustomLeaveAllocation",
    "Employee": "paie.override.employee.CustomEmployee",
 }

# Document Events
# ---------------
# Hook on document methods and events

#doc_events = {
#   "Loan": {"validate": "paie.override.utils.validate_loan_repay_from_salary"},
#		"on_update": "method",
#		"on_cancel": "method",
#		"on_trash": "method"
#	}
#}

# Scheduled Tasks
# ---------------

# scheduler_events = {
#	"all": [
#		"paie.tasks.all"
#	],
#	"daily": [
#		"paie.tasks.daily"
#	],
#	"hourly": [
#		"paie.tasks.hourly"
#	],
#	"weekly": [
#		"paie.tasks.weekly"
#	],
#	"monthly": [
#		"paie.tasks.monthly"
#	],
# }

# Testing
# -------

# before_tests = "paie.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
#	"frappe.desk.doctype.event.event.get_events": "paie.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "paie.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]


# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_3}",
#		"strict": False,
#	},
#	{
#		"doctype": "{doctype_4}"
#	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"paie.auth.validate"
# ]

fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Paie Congo"]]},
    {"dt": "Client Script", "filters": [["enabled", "=", 1],["module", "=", "Paie Congo"]]},
    {"dt": "Server Script", "filters": [["disabled", "=", 0],["module", "=", "Paie Congo"]]},
]
