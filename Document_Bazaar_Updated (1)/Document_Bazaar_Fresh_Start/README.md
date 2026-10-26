# Document Bazaar — Fresh Start

A local Flask + SQLite starter for a digital-document marketplace. This is a clean rebuild, not a production-ready payment marketplace.

## Features included
- Customer registration and sign-in
- Signed-in account name shown in the navigation
- Lead-only review dashboard
- Upload document listings for review
- Lead can approve or reject submissions
- Marketplace search and category filtering
- Demo purchase flow that adds a document to a user's library
- Protected downloads for purchased documents
- SQLite database created automatically

## Demo lead account
- Email: `lead@documentbazaar.local`
- Password: `LeadDemo123!`

This is for local testing only. Change the credentials and secret key before deployment. Do not expose the demo lead account publicly.

## Windows setup
1. Extract the ZIP to a normal folder, e.g. `C:\Users\YourName\Desktop\Document_Bazaar_Fresh_Start`.
2. Open that folder in VS Code.
3. Open Terminal > New Terminal.
4. Create a virtual environment:
   ```powershell
   py -3.11 -m venv .venv
   ```
   If Python 3.11 is unavailable, use `py -m venv .venv`.
5. Activate it:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks activation, run this for the current terminal only:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```
6. Install dependencies:
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
7. Start the website:
   ```powershell
   python app.py
   ```
8. Open `http://127.0.0.1:5000`.

## Important payment note
Purchases in this starter are **demo-only**. No card, UPI, PayU, or Razorpay payment is processed. Before charging real customers or paying sellers, implement and test a real payment gateway integration, webhook signature verification, refund handling, and a compliant marketplace payout flow. Verify PayU's current marketplace/split-settlement eligibility directly with PayU.

## Reset the local demo database
Stop the Flask server, then delete `instance/document_bazaar.db` and restart `python app.py`. This resets local users and documents. Back up any uploads first if you need them.

## Uploads
Allowed file extensions: PDF, DOC/DOCX, PPT/PPTX, TXT, XLS/XLSX, ZIP. Max upload size is 25 MB. Files are stored locally in `uploads/`; configure private object storage and malware scanning before production.

## PayU sandbox preparation (test mode only)

This starter now includes a guarded PayU Hosted Checkout test flow. It is deliberately **not production-ready** and does not yet send a marketplace `splitRequest`; real split settlements require PayU to activate the feature and each creator to be onboarded as a child merchant with the appropriate PayU identifiers/keys. Until that is confirmed, live payments remain disabled.

1. Obtain **test/sandbox** merchant credentials from PayU. Never paste credentials into chat or commit them to source control.
2. In the same PowerShell session, set the environment variables (replace the placeholders with your PayU test credentials):

```powershell
$env:PAYU_MODE = "test"
$env:PAYU_MERCHANT_KEY = "YOUR_TEST_MERCHANT_KEY"
$env:PAYU_MERCHANT_SALT = "YOUR_TEST_MERCHANT_SALT"
python app.py
```

3. Test only with PayU's sandbox/test credentials. Paid documents remain locked until the callback hash, transaction ID, merchant key, and amount are checked by the server. The success message explicitly says it was a test payment.
4. The app records an illustrative 30% platform amount and 70% creator amount in `payment_orders`. These are **accounting records only** until PayU split settlement is approved and the split API is correctly configured. Processing charges, tax, refunds, and contract terms may change the actual payable amount.
5. Do not set `PAYU_MODE=live`. This starter intentionally blocks live mode. Before production, have the integration reviewed, add PayU's required transaction verification/reconciliation and webhook handling, configure the approved split request and child merchant onboarding, use HTTPS, and set a strong `DOCUMENT_BAZAAR_SECRET`.

Official references:
- Hosted checkout and response hash validation: https://docs.payu.in/docs/prebuilt-checkout-page-integration
- Hashing request/response: https://docs.payu.in/docs/hashing-request-and-response
- Split settlements: https://docs.payu.in/docs/aggregator-or-marketplace-settlement-solution


## Update notes
- Three built-in paid resources are seeded once into SQLite from `seed_documents/` at startup.
- All public marketplace listings must have a price greater than ₹0.
- Customers can open a resource details page before purchasing.
- PayU remains restricted to sandbox/test mode. Split Settlement activation and live production payment verification are not included or claimed as complete.

Keep merchant credentials in environment variables; never commit them to source control.
