import pandas as pd

bt = pd.read_csv('backtest_june_archetype_full.csv')

print('Method distribution:')
print(bt.method.value_counts())

print('\nPerformance by method:')
for m in bt.method.unique():
    d = bt[bt.method == m]
    corr = d[['predicted_ks', 'actual_ks']].corr().iloc[0,1]
    print(f'{m}: MAE={d.abs_error.mean():.2f}, Corr={corr:.3f}, N={len(d)}')
