import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Load enriched CSV
df = pd.read_csv('hubspot-crm-exports-all-deals-2026-09-23-3_enriched.csv')

# Apply population filters
filtered = df[
    (df['eng_size'] >= 15) &
    (df['Pipeline'] == 'Classic') &
    (df['Qualified?'] == 'Qualified') &
    (pd.to_datetime(df['Create Date']) >= '2026-01-01')
].copy()

print(f"Total qualified deals matching criteria: {len(filtered)}")

# Group by eng_size_group and sum amounts
result = filtered.groupby('eng_size_group').agg({
    'Amount': 'sum',
    'Record ID': 'count'
}).rename(columns={'Record ID': 'deal_count'})

# Sort by size groups
size_order = ['15-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001+']
result = result.reindex([s for s in size_order if s in result.index])
result = result[result['Amount'] > 0]

# Calculate percentages
result['pct'] = (result['Amount'] / result['Amount'].sum() * 100)

print("\nData for pie chart:")
print(result)

# Create figure
fig, ax = plt.subplots(figsize=(16, 10))

colors = ['#4C72B0', '#DD8452', '#55A868', '#C44E52', '#8172B3', '#937860', '#CCB974']

# Create pie chart
wedges, texts, autotexts = ax.pie(
    result['Amount'], 
    labels=None,
    colors=colors[:len(result)],
    autopct='',
    startangle=90,
    wedgeprops={'edgecolor': 'white', 'linewidth': 3},
    explode=[0.02] * len(result)
)

# Add dollar amount and percentage on each wedge
for i, (idx, row) in enumerate(result.iterrows()):
    angle = (wedges[i].theta2 - wedges[i].theta1) / 2. + wedges[i].theta1
    x = np.cos(np.deg2rad(angle)) * 0.7
    y = np.sin(np.deg2rad(angle)) * 0.7
    
    ax.text(x, y, 
            f'${row["Amount"]:,.0f}\n({row["pct"]:.1f}%)',
            ha='center', va='center',
            fontsize=13, fontweight='bold',
            color='white',
            bbox=dict(boxstyle='round,pad=0.6', 
                     facecolor='black', alpha=0.8, edgecolor='white', linewidth=1.5))

# Create legend
legend_labels = [f'{idx} employees' for idx in result.index]

legend = ax.legend(
    wedges,
    legend_labels,
    title='Engineering Group Size',
    loc='center left',
    bbox_to_anchor=(1.08, 0.5),
    fontsize=14,
    title_fontsize=16,
    frameon=True,
    shadow=True,
    fancybox=True,
    borderpad=1.2,
    labelspacing=1.2
)

legend.get_frame().set_facecolor('#f8f8f8')
legend.get_frame().set_edgecolor('black')
legend.get_frame().set_linewidth(2)

ax.set_title(
    'Deal Amount by Engineering Group Size\n' +
    '(2026, Pipeline=Classic, Deal Type=New Business, Qualified)\n' +
    '(Excl. EMEA Ent, US Ent, LATAM, Exec, APJ+Ent, Sharon Peretz+Ent)',
    fontweight='bold',
    fontsize=17,
    pad=30
)

plt.tight_layout()
plt.savefig('deal_amount_pie_chart.png', dpi=150, bbox_inches='tight')
plt.show()

print(f"\nChart saved: deal_amount_pie_chart.png")
