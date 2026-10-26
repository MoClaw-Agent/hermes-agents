---
# OCR Masthead Repair — Arabic ADALA Official Journal Headers

## Problem

Arabic ADALA PDFs sometimes have garbled OCR output on the official journal masthead line. The masthead `الجريدة الرسمية العدد NNNN` ( Official Gazette issue NNNN) gets corrupted while the body text remains clean.

## Garbling Patterns Observed

### Pattern 1: Standard garbled masthead (single line)
```
((19 (مسيد 91(1( 17 ج 1 خالا يدامج 717 - 7362 عدد 9754 الجريدة الرسمية
```
Decodes to: `الجريدة الرسمية العدد 9754`

### Pattern 2: "بمسيد" prefix variant
```
((16 (1 بمسيد 6(1( 225 ج 2 خالا يدامج 525 - 476 57465 عدد 9648 الجريدة الرسمية
```
Decodes to: `الجريدة الرسمية العدد 9648`

### Pattern 3: Multi-line (number and masthead on separate lines)
```
((23 (مسيد 32(2( 28 ج 2 وألا يدامج 828 - 45177154 عدد
الجريدة الرسمية
```
Decodes to: `الجريدة الرسمية العدد 11380`

### Pattern 4: Masthead on first line, garbled text on second line (2016 variant)
```
الجريدة الرسمية 10081
((21 (مسيد 12(2( 9 رب 9 وألا عيبر 9 - 6423 عدد
```
Decodes to: `الجريدة الرسمية العدد 10081` (and remove the garbled second line)

### Pattern 3: Multi-line (number and masthead on separate lines)
```
((23 (مسيد 32(2( 28 ج 2 وألا يدامج 828 - 45177154 عدد
الجريدة الرسمية
```
Decodes to: `الجريدة الرسمية العدد 11380`

### Pattern 4: Masthead on first line, garbled text on second line (2016 variant)
```
الجريدة الرسمية 10081
((21 (مسيد 12(2( 9 رب 9 وألا عيبر 9 - 6423 عدد
```
Decodes to: `الجريدة الرسمية العدد 10081` (and remove the garbled second line)

### Pattern 5: Lowercase "رب" instead of "ج" (article ordinal variant)
```
((21 (مسيد 12(2( 9 رب 9 وألا عيبر 9 - 6423 عدد 10081 الجريدة الرسمية
```
The ordinal marker can be `رب` (رَبْع/ربع) instead of `ج` (جُزْء/جزء) depending on the PDF's OCR output. The repair regex must not anchor on either one specifically — use `.?` to match any single Arabic character in that slot.

### Pattern 6: Page 2+ masthead fragments (merge context)
On pages after the first, the masthead fragment (`الجريدة الرسمية` or its tail like `يدة الرسمية`) can appear BEFORE the garbled block, not after it:
```
الجريدة الرسمية
((16 (1 Bemسيد 6(1( 225 ج 2 خالا يدامج 525 - 476 57465 عدد
50.25 قمر قانون املاليه
```
The garbled chunk starts at `((` (or `NN (1`/`NN. (1`) and ends at `عدد`. The clean masthead replaces the entire garbled chunk — NOT the preceding masthead fragment. The regex must NOT require `الجريدة الرسمية` to follow `عدد`.

### Pattern 7: "بمسيد" with Bem prefix (page 2+ jurtheque variant)
```
((16 (1 Bemسيد 6(1( 225 ج 2 خالا يدامج 525 - 476 57465 عدد
50.25 قمر قانون املاليه
```
The `بمسيد` OCR can render as `Bemسيد` or `بمسيد` depending on the scraper. The regex alternation must cover both: `بمسيد` and the Bem-script variant. Use `.*?` between the start marker and `مسيد` to absorb any prefix.

### Pattern 8: Completely reversed OCR (unfixable by regex)
```
هديرجلا هيمسرلا
صوصن هماعددع
```
The masthead is written backwards (الجريدة الرسمية → هيرجلا هيمسرلا). The entire page is mirrored/reversed. NO regex repair can fix this — the body text is also garbled. These files (e.g. refs 32.93, 1.87.200) require manual re-OCR or mirror-reversal pre-processing at the PDF level. Flag them in the merge output for manual review.