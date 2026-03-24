# Pyodide Output Display Guide

## The Critical Rule: Last Line Must Be OUTSIDE Conditionals

In Pyodide notebooks, the **last line of code must be OUTSIDE all conditionals** (if/else/for/while) for the result to display.

### Why?

In normal Jupyter, the last expression in a cell auto-renders regardless of where it is. But in Pyodide, the notebook frontend only captures and displays the final result if it's at the top level of the code.

## ✅ CORRECT Pattern

```python
df = await query_db('SELECT * FROM raw_materials')

# Do your processing inside conditionals
if df is not None and not df.empty:
    print("Data found!")
else:
    print("No data")

# ALWAYS put the result OUTSIDE conditionals
df  # <-- This displays the table
```

## ❌ WRONG Pattern

```python
df = await query_db('SELECT * FROM raw_materials')

# Result inside conditional - WON'T DISPLAY
if df is not None and not df.empty:
    df  # <-- This won't display!
else:
    print("No data")
```

## Examples for Different Use Cases

### 1. Display a Table

```python
df = await query_db('SELECT * FROM raw_materials')

if df is not None and not df.empty:
    print("Found " + str(len(df)) + " rows")
else:
    print("No data returned")

df  # <-- Display outside conditional
```

### 2. Display a Chart

```python
import plotly.graph_objects as go

df = await query_db('SELECT date, sales FROM sales_data')

if df is not None and not df.empty:
    fig = go.Figure(
        data=go.Scatter(
            x=df['date'],
            y=df['sales'],
            mode='lines+markers'
        )
    )
    fig.update_layout(title='Sales Over Time', template='plotly_white')
else:
    fig = None
    print("No data")

fig  # <-- Display outside conditional
```

### 3. Display a Single Value

```python
result = await query_db('SELECT COUNT(*) as total FROM raw_materials')

if result is not None and not result.empty:
    total = result.iloc[0, 0]
    print("Total items: " + str(total))
else:
    total = 0
    print("No data")

total  # <-- Display the value
```

### 4. Multiple Outputs

```python
df = await query_db('SELECT * FROM products')

# Print info inside conditional
if df is not None and not df.empty:
    print("Columns: " + str(list(df.columns)))
    print("Rows: " + str(len(df)))
else:
    print("No data")

# Display the actual data outside conditional
df
```

## Key Takeaways

1. ✅ **DO**: Put result object at the very end, outside all conditionals
2. ✅ **DO**: Use print() inside conditionals for messages
3. ✅ **DO**: Use simple string concatenation: `"text: " + str(value)`
4. ❌ **DON'T**: Put df/fig inside an if block
5. ❌ **DON'T**: Use f-strings with formatting: `f"text: {value:,}"`
6. ❌ **DON'T**: Use fig.show() or plt.show()

## Testing

Try this in a cell:

```python
import plotly.graph_objects as go

# Sample data
x_data = [1, 2, 3, 4, 5]
y_data = [10, 15, 13, 17, 20]

# Create chart
fig = go.Figure(
    data=go.Scatter(
        x=x_data,
        y=y_data,
        mode='lines+markers',
        name='Sample Data',
        line=dict(color='#667eea', width=2),
        marker=dict(size=8)
    )
)

fig.update_layout(
    title='Test Chart',
    xaxis_title='X Axis',
    yaxis_title='Y Axis',
    hovermode='x unified',
    template='plotly_white',
    height=400
)

# Display outside any conditionals
fig
```

You should see an interactive chart!
