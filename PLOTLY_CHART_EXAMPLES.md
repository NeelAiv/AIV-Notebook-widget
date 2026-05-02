# Plotly Chart Examples for Pyodide Notebook

All these examples use the **go.Figure pattern** which is tested and working in your notebook.

## 1. Line Chart (with markers)

```python
import plotly.graph_objects as go

df = await query_db('SELECT SaleDate, SUM(SaleAmount) as TotalSales FROM SalesData GROUP BY SaleDate ORDER BY SaleDate')

if df is not None and not df.empty:
    fig = go.Figure(
        data=go.Scatter(
            x=df['SaleDate'],
            y=df['TotalSales'],
            mode='lines+markers',
            name='Total Sales',
            line=dict(color='#667eea', width=2),
            marker=dict(size=6)
        )
    )
    
    fig.update_layout(
        title='Sales Over Time',
        xaxis_title='Date',
        yaxis_title='Total Sales',
        hovermode='x unified',
        template='plotly_white',
        height=400
    )
    fig
else:
    print("No data returned")
```

## 2. Bar Chart

```python
import plotly.graph_objects as go

df = await query_db('SELECT ProductName, SUM(Quantity) as TotalQty FROM SalesData GROUP BY ProductName LIMIT 10')

if df is not None and not df.empty:
    fig = go.Figure(
        data=go.Bar(
            x=df['ProductName'],
            y=df['TotalQty'],
            name='Quantity',
            marker=dict(color='#764ba2')
        )
    )
    
    fig.update_layout(
        title='Product Sales Quantity',
        xaxis_title='Product',
        yaxis_title='Total Quantity',
        hovermode='x unified',
        template='plotly_white',
        height=400
    )
    fig
else:
    print("No data returned")
```

## 3. Scatter Plot

```python
import plotly.graph_objects as go

df = await query_db('SELECT Price, Quantity FROM SalesData LIMIT 100')

if df is not None and not df.empty:
    fig = go.Figure(
        data=go.Scatter(
            x=df['Price'],
            y=df['Quantity'],
            mode='markers',
            name='Sales',
            marker=dict(
                size=8,
                color='#f093fb',
                opacity=0.7,
                line=dict(width=1, color='#667eea')
            )
        )
    )
    
    fig.update_layout(
        title='Price vs Quantity',
        xaxis_title='Price',
        yaxis_title='Quantity',
        hovermode='closest',
        template='plotly_white',
        height=400
    )
    fig
else:
    print("No data returned")
```

## 4. Histogram

```python
import plotly.graph_objects as go

df = await query_db('SELECT SaleAmount FROM SalesData')

if df is not None and not df.empty:
    fig = go.Figure(
        data=go.Histogram(
            x=df['SaleAmount'],
            nbinsx=30,
            name='Sales Amount',
            marker=dict(color='#667eea')
        )
    )
    
    fig.update_layout(
        title='Distribution of Sales Amounts',
        xaxis_title='Sale Amount',
        yaxis_title='Frequency',
        template='plotly_white',
        height=400
    )
    fig
else:
    print("No data returned")
```

## 5. Multiple Lines (Comparison)

```python
import plotly.graph_objects as go

df = await query_db('SELECT Month, Revenue, Expenses FROM MonthlyData ORDER BY Month')

if df is not None and not df.empty:
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df['Month'],
        y=df['Revenue'],
        mode='lines+markers',
        name='Revenue',
        line=dict(color='#667eea', width=2),
        marker=dict(size=6)
    ))
    
    fig.add_trace(go.Scatter(
        x=df['Month'],
        y=df['Expenses'],
        mode='lines+markers',
        name='Expenses',
        line=dict(color='#f093fb', width=2),
        marker=dict(size=6)
    ))
    
    fig.update_layout(
        title='Revenue vs Expenses',
        xaxis_title='Month',
        yaxis_title='Amount',
        hovermode='x unified',
        template='plotly_white',
        height=400
    )
    fig
else:
    print("No data returned")
```

## 6. Pie Chart

```python
import plotly.graph_objects as go

df = await query_db('SELECT Category, SUM(SaleAmount) as Total FROM SalesData GROUP BY Category')

if df is not None and not df.empty:
    fig = go.Figure(
        data=go.Pie(
            labels=df['Category'],
            values=df['Total'],
            marker=dict(colors=['#667eea', '#764ba2', '#f093fb', '#4facfe'])
        )
    )
    
    fig.update_layout(
        title='Sales by Category',
        height=400
    )
    fig
else:
    print("No data returned")
```

## Key Points:

✅ **All examples use `go.Figure` pattern** - tested and working
✅ **No `fig.show()`** - just return `fig`
✅ **No `px.express`** - use `go.Scatter`, `go.Bar`, etc.
✅ **Always end with `fig`** - this triggers display
✅ **Use `await query_db()`** - for real database data
✅ **Check for empty data** - always validate before plotting

## Color Palette (Vibrant):

- Primary: `#667eea` (Purple)
- Secondary: `#764ba2` (Dark Purple)
- Accent: `#f093fb` (Pink)
- Light: `#4facfe` (Blue)

Just ask the AI to create any of these chart types and it will generate code following this pattern!
