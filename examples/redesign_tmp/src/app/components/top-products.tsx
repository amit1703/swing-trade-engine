import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Progress } from "./ui/progress";

const products = [
  {
    name: "Premium Headphones",
    sales: 1234,
    revenue: "$32,450",
    progress: 85,
    color: "bg-emerald-500",
  },
  {
    name: "Wireless Mouse",
    sales: 987,
    revenue: "$24,870",
    progress: 72,
    color: "bg-cyan-500",
  },
  {
    name: "Mechanical Keyboard",
    sales: 756,
    revenue: "$18,900",
    progress: 58,
    color: "bg-purple-500",
  },
  {
    name: "USB-C Cable",
    sales: 543,
    revenue: "$12,300",
    progress: 45,
    color: "bg-pink-500",
  },
  {
    name: "Phone Stand",
    sales: 432,
    revenue: "$8,640",
    progress: 38,
    color: "bg-orange-500",
  },
];

export function TopProducts() {
  return (
    <Card className="bg-gray-900/50 border-gray-800 backdrop-blur-sm">
      <CardHeader>
        <CardTitle className="text-gray-200 font-mono uppercase tracking-wide">Top Products</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {products.map((product, index) => (
            <div key={index} className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <p className="text-sm font-medium text-emerald-400 font-mono">
                    {product.name}
                  </p>
                  <p className="text-xs text-gray-500 font-mono">
                    {product.sales} sales
                  </p>
                </div>
                <span className="text-sm font-semibold text-cyan-400 font-mono">
                  {product.revenue}
                </span>
              </div>
              <div className="relative h-2 bg-gray-800 rounded-full overflow-hidden">
                <div 
                  className={`h-full ${product.color} rounded-full transition-all duration-300`}
                  style={{ width: `${product.progress}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}