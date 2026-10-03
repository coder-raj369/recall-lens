# RecallLens: answering "is mine recalled?", and knowing when not to

A recall notice rarely recalls a product. It recalls some units of it: lots 1276118 and 1276119, model years 2021 to 2023, serial numbers in a range, everything made between two dates. So "has my antacid been recalled?" is two questions. Which notice is about this product? And is *this unit* inside what the notice covers?

Search answers the first. It cannot answer the second, and the second is the one that matters. RecallLens is a system built around that gap, and this is an account of what building and measuring it showed.

## What it does

A person types a description or photographs a label. The system reads the photo (OWLv2 finds the label regions, Florence-2 reads them, barcodes and VINs are decoded directly), pulls out the identifiers that decide recall status, retrieves candidate notices from 18,490 CPSC, FDA and NHTSA recalls, and checks each candidate's scope against the unit in code. The answer is one of three: covered, not covered, or a question about the one detail that would settle it. Each answer cites the notice and quotes the sentence it relied on.

The steps run as a LangGraph graph that streams its progress, pauses for a clearer photo and resumes. The verdict comes from rules, not from a language model: Claude arbitration for the cases the rules cannot decide is built, tested against a mocked API and switched off, because the budget for this project is $0.

## Four things the measurements changed

**Search is not an answer.** On 150 held-out cases, run once, treating every retrieved notice as a match is right 41% of the time and raises a false alarm for every product that is not recalled. Matching only on a listed code looks safer and is worse where it counts: it misses 48% of recalled units, because recalls of every unit and recalls of vehicles list no code to match. Checking scope in code was right 85% of the time, missed 3% and raised a false alarm on 6%.

**A wrong "not affected" hides in what a notice leaves out.** Building the test cases, before anything was measured, turned up two ways to rule a unit out wrongly: 178 notices keep part of their code list somewhere else, such as an attachment, and extraction had missed lot codes that the text plainly lists. A unit absent from an incomplete list is not a safe unit. Those paths now ask a question. The primary metric through the whole project is the false-negative rate, and a question is always an allowed answer.

**A fresh test set keeps the numbers honest.** The first test split found real problems, and scoring their fixes on the same split would have measured nothing. So the fixes were scored on those 150 new cases, built afterwards from recalls no other split uses: 85%, not the 93% the seen split showed. The gap was itself useful. It named two rule problems the seen split could not show, and with those fixed the same cases score 93%, which is no longer an unseen result and is reported as such.

**Five candidates are not enough for a car.** One of those problems was vehicle recalls asking "which model is yours?" of people who had named their model. Fixing it removed a question that had been hiding a retrieval failure: a popular model has dozens of recalls, a check compares the five that search ranks first, and when those five covered other model years the answer read "not your model year" while another notice covered it. A check over 600 vehicles drawn from the recalls' own lists found 7 answered wrongly or with a question. Notices that list the named make, model and model year are now looked up exactly, ahead of search, and 3,000 such vehicles are all answered "covered". Questions on vehicles that no recall lists fell from 406 in 600 to 34.

That last change shows the method. The vehicle sweep is not a hand-labeled set. It follows from the data: a vehicle a recall lists is covered by construction, so any other answer is an error. Checks of this kind cost nothing to label and reach parts of the corpus that 300 hand-built cases do not.

## What it costs

A text check takes 0.11 s at the median on an 8 GB laptop, nearly all of it in retrieval, and the API answers about 20 checks a second at eight concurrent. Rules-only checks make no model calls. With arbitration on, an estimated 46% of checks would call Claude once, for $13 to $40 per 1,000 checks; the figure comes from the exact prompts that would be sent, and nothing was sent.

Every change is gated. CI replays the verification step on all 300 recorded cases in seconds and fails any change that adds a missed recall or an unsafe answer.

## What is still wrong

- **Photos are the weakest input**, right on 67% of held-out cases. When OCR misreads the one code that distinguishes a unit ("CCA0558" for CCA06582), search never finds the notice. Photos with nothing legible need visual search, which is not built.
- **A base name can claim a different model.** An "Escape PHEV" is shown recalls of the "Escape". That is right when the maker lists one name for every version and a false alarm when it does not. The rules prefer the false alarm.
- **Makes are matched as written.** "Chevy" is not Chevrolet, so those questions fall back on search.
- **Email alerts have not met a real mail server.** The watchlist re-checks watched products and emails new matches; it is tested with a stand-in server and was dry-run on the real corpus.
- **One agency is missing.** USDA FSIS blocks automated clients, so meat and poultry recalls are not covered.

## Run it

```bash
docker compose up --build    # database, app and the last 30 days of recalls
```

Then open http://localhost:8000. The [README](../README.md) has the results in full and the [decision records](adr/README.md) the reasons behind the design.
