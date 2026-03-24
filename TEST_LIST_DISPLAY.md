# Test: List Display Fix

## What Changed

Fixed the issue where "list of raw materials" query wasn't displaying output.

### Root Cause
The generated code had conditional branches where the final `df` statement wasn't guaranteed to execute in all paths. The frontend needs a result object at the end of the code to display it.

### Solution
Updated the code generation template to ensure `df` is always returned, even in the error case:

```python
# OLD (broken):
if df is not None and not df.empty:
    if len(df) == 1 and len(df.columns) == 1:
        print(...)
    else:
        df  # <-- Only returned in this branch
else:
    print("No data returned")  # <-- No return here!

# NEW (fixed):
if df is not None and not df.empty:
    if len(df) == 1 and len(df.columns) == 1:
        print(...)
    df  # <-- Always returned after if block
else:
    print("No data returned")
    df  # <-- Also returned in error case
```

## Test It

Ask the AI:
- "list of raw materials"
- "show all products"
- "display inventory"
- "get all customers"

You should now see a formatted table with all the data!

## Expected Output

A beautifully styled table with:
- Purple gradient headers
- Alternating white/gray rows
- Hover effects
- Horizontal scroll for wide tables
