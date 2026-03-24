# Pyodide-compatible Plotly chart test
# Copy and paste this entire cell into your notebook

import plotly.graph_objects as go

# Create sample data for a simple line chart
x_data = [1, 2, 3, 4, 5]
y_data = [10, 15, 13, 17, 20]

# Create a line chart
fig = go.Figure(
    data=go.Scatter(
        x=x_data,
        y=y_data,
        mode='lines+markers',
        name='Sample Data',
        line=dict(color='#1f77b4', width=2),
        marker=dict(size=8)
    )
)

# Update layout for better appearance
fig.update_layout(
    title='Plotly Chart Rendering Test',
    xaxis_title='X Axis',
    yaxis_title='Y Axis',
    hovermode='x unified',
    template='plotly_white',
    height=400
)

# Display the chart (Pyodide will render this automatically)
fig
