# First-time Windows installation — v0.2.6

1. Install Docker Desktop and enable **Start Docker Desktop when you sign in**.
2. Extract the full package to a permanent folder such as `D:\ProductionReviewWebApp`.
3. Start Docker Desktop and wait until Docker Engine is ready.
4. Double-click `start_windows.bat`.
5. Open `http://localhost:5173` and sign in with the development credentials shown in README.
6. Before shared use, change `.env` secret/admin password.

## Fresh-data import sequence

- Verify/import Product Master.
- Import Historical Sales Price revisions.
- Import Historical Daily MIS.
- Import Historical Rejection data after its remaining inputs are completed.
- Begin normal daily operation.

Persistent data is stored only in the `database/` folder. Do not delete it after go-live.
