# সূত্র (Sutro) — জেলা/উপজেলা ভিত্তিক খতিয়ান অনুসন্ধান + Digital Deed Verification

**Hackathon prototype — sample CSVs and admin-published uploads.** The site is **not** a Bangladesh government website, and neither a located khatian nor a signed demo PDF is proof of legal ownership. Khatian lookup uses structured records. Admin image uploads use local OCR to propose a draft for review. The frontend is HTML, CSS, and vanilla JavaScript; Flask handles SQLite, signed PDFs and image serving.

## Admin panel

Restart the server after updating the project, then open **http://127.0.0.1:5000/admin**.
On first use, set a password of **12–128 characters** and confirm it. Initial setup is
available only from the local computer. Alternatively, set `SUTRO_ADMIN_PASSWORD`
in `.env` before the first startup; it initializes the account only once.
Passwords are stored as hashes, and authenticated sessions expire after eight hours.
Use the password tab to change the password; this invalidates other admin sessions.

The admin panel provides:

- **Khatian image upload:** JPG, PNG or WEBP, up to 15 MB and 40 million pixels.
  A draft and private image preview are saved immediately. Local Bengali/English
  Tesseract OCR proposes labelled fields and readable owner names. OCR is not an
  ownership verification service: review the source image and correct the fields,
  owner shares and dag rows before selecting **Publish**. Incomplete drafts can be saved.
- **Publication:** published records and their locations become available in the
  public search. Drafts and unpublished images require admin login. CSVs remain unchanged.
- **Deed creation:** add deed fields and download a signed demo PDF with QR code.
  Public visitors can verify/download published deeds; creating deeds requires admin login.
  Bengali Unicode text is embedded using the included OFL-licensed Noto font.
  PDF text stays in logical character order for verification; complex Bengali
  conjunct typography can differ from browser-rendered text.
- **All records:** search and paginate through sample khatians, uploaded khatians,
  drafts and deeds. View images, record fields and signed PDFs.
- **Warnings:** set or clear a public warning on a khatian or deed. Deed warnings
  also appear in upload verification and QR lookup results.
- **Delete / Restore:** deletion removes a record and its image/PDF from public
  access. Admins can still view and restore it. The underlying record, file, CSV
  and audit history are retained; this is a recoverable deletion.

OCR needs the Tesseract executable and the `ben` and `eng` traineddata files.
This computer's `C:\Program Files\Tesseract-OCR\tesseract.exe` is auto-detected.
On other computers, put Tesseract on PATH or set `SUTRO_TESSERACT_CMD` in `.env`.
If OCR is unavailable or times out, the image draft is still saved and can be
filled manually. See the [official Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html).

Back up **the entire `instance` directory**: it contains the SQLite registry,
uploaded files, signing keys and session secret. These files are excluded from Git.
For an HTTPS deployment set `SUTRO_COOKIE_SECURE=1`; set the initial password
before exposing the server. The default deployment remains local.

Run the tests with `python -m unittest discover -s tests -v`.

## Private land complaints

Visitors can open **`/complaints`** from the home navigation to submit a land
complaint without an admin account. Categories include encroachment, boundary
disputes, forged documents, ownership disputes, mutation/record problems,
harassment and other land-related issues. The form collects contact information,
location, a subject and detailed description, with optional khatian/dag numbers.

Up to **five PDF/JPG/PNG/WEBP attachments** can be submitted: **5 MB per file,
10 MB combined**. File contents are validated. Files are stored privately under
`instance/complaints/`, outside the public static directory, and included in the
existing full-instance backup recommendation. A submitter receives a receipt ID.
At **`/complaints#track`**, that number can be used to check the current status and
submission/update times. The tracking endpoint returns only these status fields;
there is no public complaint-detail lookup, list or attachment access, even with that ID.
Anyone holding the complete number can check its status, so retain it privately.
Complaint contents, filenames and admin notes are also excluded from public audit
and dashboard APIs. Submission requires a form session token and is limited to ten
complaints per hour per source address.

The admin panel's **Complaint Management** tab shows a new-complaint badge and
refreshes it every minute while the page is visible. Admins can search/filter
complaints, view full details, download supporting documents, mark complaints as
read/reviewing/resolved/closed, and save private notes. Opening a new complaint
marks it read. All management and document endpoints require admin authentication;
updates also require the existing session token.

**Forward to Land Office** is an English placeholder button, disabled with a
“Coming soon” explanation. There is no forwarding endpoint or external office
integration, and no complaint is marked as forwarded or sent anywhere. This
platform is not a government complaint-filing service.

## Local deed image lookup and copy matching

The home page now includes a separate local-deed section. Set
`SUTRO_DOLIL_IMAGE_DIR` to your image folder; this project is configured for
`C:\gol tanvir\Dolil` (588 JPG copies at setup). Filenames supply the lookup
number: **`dolil_1.jpg` → `1`**. This is an image identifier, not a claim that
the handwritten/legal deed number inside the scan is 1. Bangla digits and
`dolil_1` are accepted. New images in the folder are picked up automatically.

- Find a local copy by number and open its image.
- Upload JPG/PNG/WEBP and provide the number, or let a filename such as
  `dolil_1.jpg` supply it. The uploaded copy is processed in memory and not saved.
- `EXACT_FILE_MATCH` means identical file bytes. `EXACT_IMAGE_MATCH` means identical
  decoded image pixels, including image size and transparency, after EXIF orientation.
- `NOT_EXACT_MATCH` means the images are not identical. Compression, resizing,
  photography or edits can cause this result; it is not a fraud determination.
- Ambiguous duplicate filenames for the same number are rejected rather than
  choosing one. Only supported, numbered files inside the configured folder are served.
- Admins can select **Local deed images** in the record list to view copies,
  set warnings, delete from public access, and restore. Source files are not modified.

This does **not** authenticate legal deeds, signatures or ownership and does not
perform OCR on handwritten documents. The existing signed Sutro PDF verification
remains available separately.

The home page's lower admin section has been removed. It now offers complaint
submission and tracking links; administration remains available at `/admin`.

## Home page and digital deed generation

Select **Generate digital deed** from the home navigation, the generation card,
or the footer. The action opens **`/admin#deed`**; after admin sign-in it opens the
existing deed creation form directly, where a signed demo PDF with QR can be generated.

The home page includes an animated document illustration and a pause-animation
control. Reduced-motion preferences disable the animation automatically. The
**Sutro in numbers** section loads `/api/insights`: a survey donut chart, district
bar chart and totals for publicly available local khatians, deed images and signed
demo deeds. Chart values can also be viewed as tables; survey legend buttons
highlight a survey. Refresh reloads current values, and Bangla/English switching
updates chart labels. Deleted records, unpublished drafts and private complaints
are excluded. These are local site statistics, not nationwide land-record coverage.

The About section includes the supplied team members and faculty/industry mentors,
their contact details, and the teammate-edit link. The footer links to generation,
lookup, verification, complaints, tracking and About.

## আপডেটেড খতিয়ান সার্চ কীভাবে কাজ করে?

সার্চের ধাপ হলো **জেলা → উপজেলা/থানা → মৌজা (ঐচ্ছিক) → খতিয়ান নম্বর → জরিপ (ঐচ্ছিক)**। বাংলা অঙ্ক (যেমন `৮৫০`) অথবা ইংরেজি অঙ্ক (`850`) কাজ করে। জেলা এবং উপজেলা নির্বাচন বাধ্যতামূলক। মৌজা না বাছলে নির্বাচিত উপজেলার সব মৌজায় নম্বরটি খোঁজা হয়।

সফল অনুসন্ধানগুলো **সাম্প্রতিক অনুসন্ধান** হিসেবে একই ব্রাউজারের `localStorage`-এ সর্বোচ্চ পাঁচটি পর্যন্ত রাখা হয়। সার্চ কার্ডের চিপে ক্লিক করলে একই জেলা, উপজেলা, মৌজা, জরিপ ও খতিয়ান নম্বর দিয়ে আবার অনুসন্ধান করা যায়; **সব মুছুন** বাটনটি স্থানীয় তালিকাটি সরিয়ে দেয়। এই তথ্য সার্ভারে পাঠানো বা অ্যাকাউন্টের সঙ্গে সংরক্ষণ করা হয় না।

তোমার **৫টি source CSV** থেকে ডেটা নেওয়া হয়েছে:

| CSV | ডেটা | join key |
|---|---|---|
| `lands.csv` | বিভাগ, জেলা, উপজেলা, মৌজা, JL নম্বর | `land_id` |
| `khatians.csv` | খতিয়ান নম্বর, জরিপ, সাল, শিট, ছবির filename | `land_id`, `khatian_id` |
| `owners.csv` | মালিকের নাম, পিতা/স্বামী, অংশ | `khatian_id` |
| `dag_rows.csv` | দাগ নম্বর, জমির শ্রেণি, পরিমাণ | `khatian_id` |
| `title_line.csv` | আগের/পরের খতিয়ান সংস্করণ ও পরিবর্তনের ধরন | `from_khatian_id`, `to_khatian_id` |

ডেটাসেটে মোট **২,০০০টি land record**, **৫,৭৯৪টি খতিয়ান**, **২৩,১২০টি owner row**, **৩১,৫৭২টি dag row** এবং **৩,৭৯৪টি version transition** আছে। `annotations.jsonl`-এ image annotations/coordinates আছে; সেটি basic search-এর জন্য প্রয়োজন নেই, তাই বড় (৪৪MB) JSONL ফাইলটি ZIP-এ রাখা হয়নি।

### তোমার ডেটা অনুযায়ী নির্দিষ্ট উদাহরণ

- জেলা: **সিলেট**
- উপজেলা: **বিয়ানীবাজার**
- মৌজা: **উত্তরপাড়া**
- খতিয়ান নম্বর: **850** / **৮৫০**
- জরিপ: **RS**

ফলাফল হিসেবে `L00000-v0` রেকর্ড, linked ছবির preview, মালিক ও দাগের তথ্য দেখতে পাবে। খতিয়ান নম্বরটি অন্য এলাকাতেও থাকলেও এখানে অন্য এলাকার ছবি দেখাবে না।

## Windows-এ নতুন version চালানো

আগের কাজ নষ্ট না করে **নতুন** folder-এ ZIP extract করো, যেমন `C:\SutroGeo`। `C:\gol tanvir`-এর আগের `khatian` ছবিগুলো ওই জায়গাতেই রাখতে পারো।

```powershell
cd "C:\SutroGeo"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

এবার browser-এ **http://127.0.0.1:5000** খোলো। আগে কোনো Sutro instance port 5000-এ চললে পুরোনো PowerShell-এ `Ctrl+C` চাপ দিয়ে সেটি বন্ধ করো।

**`.env`-এ ছবিগুলোর location** (`C:\gol tanvir\khatian`) ঠিক আছে কি না নিশ্চিত করো:

```env
SUTRO_KHATIAN_IMAGE_DIR=C:\gol tanvir\khatian
HOST=127.0.0.1
PORT=5000
```

### ছবিগুলোর folder structure

CSV-এর image path যেমন `train/L00000-v0.jpg`। ছবিগুলো নিম্নের যেকোনো এক ধরনের folder-এ রাখতে পারো:

```text
C:\gol tanvir\khatian\L00000-v0.jpg
C:\gol tanvir\khatian\L00000-v1.jpg
```

অথবা:

```text
C:\gol tanvir\khatian\train\L00000-v0.jpg
C:\gol tanvir\khatian\train\L00000-v1.jpg
C:\gol tanvir\khatian\val\...
C:\gol tanvir\khatian\test\...
```

ZIP-এ সব **পাঁচটি CSV** এবং মাত্র **একটি sample preview JPG** আছে। হাজার হাজার আসল JPG ফাইল এই ZIP-এ নেই; সেগুলো তোমার কম্পিউটারের `khatian` folder-এ থাকতে হবে। ছবির filename CSV-এর `image_file`-এর filename-এর সঙ্গে মেলাতে হবে। ছবি না পেলে সাইটে `Image not found` দেখাবে—ভুল ছবি দিয়ে পূরণ করবে না।

## আগের Sutro ফিচারগুলোও আছে

- Synthetic deed registration ও canonical JSON-এর SHA-256 digest
- Ed25519 digital signature, public-key endpoint (`/api/public-key`)
- QR-সহ PDF export ও PDF upload verification
- Field mismatch / tamper demonstration
- Demo double-selling conflict warning, hash-chain audit timeline
- Bangla / English switch, responsive mobile/desktop UI

**দলিলের PDF verification আগে যেমন ছিল, তেমনই আছে।** সরাসরি খতিয়ান lookup-এ OCR লাগে না। ছবির লেখা OCR দিয়ে যাচাইয়ের দাবি করা হচ্ছে না। Tesseract install করা থাকলেও এই নতুন CSV search চালাতে Tesseract প্রয়োজন নেই।

### পূর্বের demo database রাখতে চাইলে

আগের folder-এর `instance`-এ যদি private key ও SQLite DB থাকে, নতুন folder-এর `instance`-এ সেগুলো **copy** করো; move/delete করো না। পুরোনো source ও `.env`-এর backup রাখবে। পুরোনো signing key হারিয়ে গেলে ওই key দিয়ে signed পুরোনো দলিল আর verify হবে না।

## নতুন API

- `GET /api/khatian/filters`: available জেলা–উপজেলা–মৌজা combinations
- `GET /api/khatian/search?district=সিলেট&upazila=বিয়ানীবাজার&mouza=উত্তরপাড়া&q=৮৫০&survey=RS`: exact geo-filtered search, owner rows, dag rows, transitions, image URL
- `GET /api/khatian-image/L00000-v0`: CSV-mapped local JPG image

Previous `/api/deeds/*`, `/api/verify`, `/api/audit`, `/api/public-key` endpoints remain.

## Official district, upazila and mouza directory

The location dropdowns include the public directory downloaded from
[the government DLRMS land portal](https://dlrms.land.gov.bd/), stored offline in
`data/land_locations.json`. This directory is separate from the synthetic CSVs:
adding an official location does not add government khatian records or images.
Sample-only locations remain selectable so the original demo still works.

The 17 October 2026 snapshot contains **64 districts**, **527 upazila/thana/revenue
circle entries**, and **123,477 mouza/JL entries** across mutation and assigned
survey lists. These are directory entries, not a count of unique physical mouzas.
The portal returned no published mouzas for 27 of the listed areas.

Districts and upazilas load first. Selecting an upazila loads its mouzas through
`GET /api/khatian/filters?district=...&upazila=...`. Unicode-equivalent Bangla
spellings match the existing CSV search. The response includes source, download
time, completion status and directory counts.

In the public khatian search, **★ marks districts, upazilas and mouzas that have
searchable khatian records in the local database**. Starred options appear first;
their underlying location values stay unchanged. Availability includes sample CSV
records and published admin uploads, excluding deleted records and drafts. It does
not imply that every khatian number or source image is available for that area.

After selecting a district and upazila, the khatian search also suggests available
numbers in a dropdown and in the number input's autocomplete. Selecting a mouza or
survey narrows this list. Choose a suggestion to fill the number field, then search,
or type a number manually. `/api/khatian/numbers` groups duplicate numbers with
their surveys and mouzas, sorts them numerically, and excludes drafts and deleted
records. The dropdown refreshes on location/survey changes; late responses from
older selections are discarded.

## Admin accounts

The first local setup creates a `superadmin` account. After signing in at `/admin`,
the super admin can open **Password / অ্যাডমিন অ্যাকাউন্ট** and register multiple
named admin accounts. Regular admins can use the existing upload, review, deed,
complaint and record-management tools, but only the super admin can create or
disable other admin accounts. Disabled accounts cannot log in. Passwords are
stored as Werkzeug password hashes, and the existing login rate limit and CSRF
protection apply to every account.

## Land fee calculator

The public home page includes an illustrative land-cost calculator. It accepts a
deed/land value and area, then lets the visitor include registration, stamp/deed,
local-tax/other, certified deed copy, certified khatian copy, mutation assistance,
and record-search lines. The percentage and fixed values are clearly presented as
demo estimates; they are not an official quote and should be checked against the
relevant office or official portal before payment.

To refresh the directory with an internet connection:

```powershell
python scripts/sync_land_locations.py
```

The downloader uses the portal's normal public session and public location APIs.
It collects mutation mouza lists and all surveys assigned to each upazila,
including revenue circles listed by the portal. Completed areas are checkpointed;
rerunning resumes interrupted downloads. To fetch a completely fresh snapshot,
back up and rename `data/land_locations.json` before running the command.
No portal tokens, deeds, or owner information are stored by this downloader.
The snapshot covers locations returned by the portal at download time; areas with
no published mouzas have an empty official list.

## Limitations

- Khatian search matches structured CSV data and reviewed admin uploads. Upload OCR proposes draft fields; it does **not** certify the source image contents.
- Deed verification certifies matching demo-signed records, **not** legal title or official ownership.
- Conflict alerts are simple demo rules, not an authoritative judgment.
- Locally served images must be present. Don't expose this development server publicly; official use would require authentication, authorization, privacy review, and a trusted registry.
