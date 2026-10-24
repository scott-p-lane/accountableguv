const tableauDashboards = Object.freeze({
  'net-income-yearly': {
    embed: 'https://public.tableau.com/views/USIncomeandSpending-YoYComparisons/SpendingDashboard?:showVizHome=no',
    share: 'https://public.tableau.com/app/profile/scott.lane7297/viz/USIncomeandSpending-YoYComparisons/SpendingDashboard',
  },
});

document.querySelectorAll('[data-tableau-dashboard]').forEach((element) => {
  const dashboardId = element.getAttribute('data-tableau-dashboard');
  const dashboard = tableauDashboards[dashboardId];

  if (!dashboard) {
    console.error(`Unknown Tableau dashboard identifier: ${dashboardId}`);
    return;
  }

  if (element.tagName === 'A' || element.tagName === 'TABLEAU-VIZ') {
    const url = element.tagName === 'A' ? dashboard.share : dashboard.embed;
    element.setAttribute(element.tagName === 'A' ? 'href' : 'src', url);
    return;
  }

  console.error(`Unsupported Tableau dashboard reference element: ${element.tagName}`);
});
