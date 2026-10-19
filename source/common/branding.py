"""The product's DISPLAY name, in one place. Changing the brand is a
one-line edit here (PRODUCT_NAME, and BUNDLE_ID/PRODUCT_TAGLINE if you want
them to match); nothing stored on a user's computer is keyed to it.

What shows the brand: page titles and headings, the login screen, the web
app manifest, the Plaid Link window, exports, and the Mac app's name,
icon label and bundle id (scripts/build_mac_app.sh reads this file).

INTERNAL_ID is the opposite: a fixed, brand-free identifier for everything
that holds user data -- the Keychain service (Plaid keys, login password)
and the Application Support folder. NEVER change it: doing so would
orphan every existing install's saved secrets and data.
"""

PRODUCT_NAME = "FinSi"
PRODUCT_TAGLINE = "Financial Super Intelligence"
PRODUCT_HEADLINE = "Your financial future, intelligently planned."
PRODUCT_MOTTO = "See your future. Shape your retirement and Legacy."
PRODUCT_SUBLINE = "Track your wealth. Anticipate your needs. Retire with confidence."
BUNDLE_ID = "com.finsi.app"

INTERNAL_ID = "RetirementPlan"

# Shown on the About card and the Mac app's Info.plist (build_mac_app.sh reads it).
APP_VERSION = "1.1.0"
# Where to send questions; leave empty until a real address exists.
SUPPORT_EMAIL = ""
