# Fixed: Double Display Issue

## The Problem

The generated code had incorrect indentation causing the `else` clause to be paired with the wrong `if` statement.

### ❌ WRONG (What was generated):

```python
if df is not None and not df.empty:
    if len(df) == 1 and len(df.columns) == 1:
        result_value = df.iloc[0, 0]
        col_name = str(df.columns[0])
        print("=" * 50)
        print(col_name + ": " + str(result_value))
        print("=" * 50)
    else:  # <-- WRONG: This else is for the inner if!
        print("No data returned")  # <-- Prints even when data exists!

df  # <-- Displays df
df  # <-- Displays df AGAIN (appears as 2 visuals)
```

**Result**: 
- When data exists: Prints "No data returned" (wrong!) + displays df twice
- When data is empty: Prints "No data returned" + displays empty df

### ✅ CORRECT (Fixed):

```python
if df is not None and not df.empty:
    if len(df) == 1 and len(df.columns) == 1:
        result_value = df.iloc[0, 0]
        col_name = str(df.columns[0])
        print("=" * 50)
        print(col_name + ": " + str(result_value))
        print("=" * 50)
else:  # <-- CORRECT: This else is for the outer if!
    print("No data returned")

df  # <-- Displays df ONCE
```

**Result**:
- When data exists: Displays df nicely formatted table
- When data is empty: Prints "No data returned"

## Key Difference

The `else` clause should be at the **same indentation level** as the outer `if`, not the inner `if`.

```
if df is not None and not df.empty:        # Outer if
    if len(df) == 1 and len(df.columns):   # Inner if
        # handle single value
else:                                       # Paired with OUTER if
    print("No data returned")
```

## Now Try Again

Ask the AI: "list of raw materials"

You should see:
- ✅ A single, beautifully formatted table
- ✅ No duplicate displays
- ✅ Proper error message if no data
