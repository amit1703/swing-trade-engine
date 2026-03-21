import { DashboardHeader } from "./components/dashboard-header";
import { Sidebar } from "./components/sidebar";
import { StatsCards } from "./components/stats-cards";
import { RevenueChart } from "./components/revenue-chart";
import { RecentActivity } from "./components/recent-activity";
import { TopProducts } from "./components/top-products";

export default function App() {
  return (
    <div className="size-full flex bg-[#0f0f14]">
      <Sidebar />
      <div className="flex-1 flex flex-col min-h-screen overflow-auto">
        <DashboardHeader />
        <main className="flex-1 p-6 space-y-6">
          <StatsCards />
          
          <div className="grid gap-6 lg:grid-cols-7">
            <div className="lg:col-span-4">
              <RevenueChart />
            </div>
            <div className="lg:col-span-3">
              <TopProducts />
            </div>
          </div>

          <RecentActivity />
        </main>
      </div>
    </div>
  );
}