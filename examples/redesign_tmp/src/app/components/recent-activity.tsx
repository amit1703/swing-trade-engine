import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Avatar, AvatarFallback, AvatarImage } from "./ui/avatar";
import { Badge } from "./ui/badge";

const activities = [
  {
    user: "Sarah Johnson",
    action: "completed order",
    orderId: "#3492",
    time: "2 minutes ago",
    avatar: "https://images.unsplash.com/photo-1758873268663-5a362616b5a7?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxtb2Rlcm4lMjBvZmZpY2UlMjB0ZWFtJTIwY29sbGFib3JhdGlvbnxlbnwxfHx8fDE3NzM5OTIyNzF8MA&ixlib=rb-4.1.0&q=80&w=1080",
    initials: "SJ",
    status: "success",
  },
  {
    user: "Michael Chen",
    action: "left a review",
    orderId: "#3489",
    time: "15 minutes ago",
    avatar: "https://images.unsplash.com/photo-1759661966728-4a02e3c6ed91?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w3Nzg4Nzd8MHwxfHNlYXJjaHwxfHxhbmFseXRpY3MlMjBkYXRhJTIwdmlzdWFsaXphdGlvbnxlbnwxfHx8fDE3NzM5ODY4Nzh8MA&ixlib=rb-4.1.0&q=80&w=1080",
    initials: "MC",
    status: "info",
  },
  {
    user: "Emily Rodriguez",
    action: "requested refund",
    orderId: "#3467",
    time: "1 hour ago",
    avatar: "",
    initials: "ER",
    status: "warning",
  },
  {
    user: "David Kim",
    action: "placed new order",
    orderId: "#3501",
    time: "2 hours ago",
    avatar: "",
    initials: "DK",
    status: "success",
  },
  {
    user: "Lisa Anderson",
    action: "updated profile",
    orderId: "",
    time: "3 hours ago",
    avatar: "",
    initials: "LA",
    status: "info",
  },
];

export function RecentActivity() {
  return (
    <Card className="bg-gray-900/50 border-gray-800 backdrop-blur-sm">
      <CardHeader>
        <CardTitle className="text-gray-200 font-mono uppercase tracking-wide">Recent Activity</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {activities.map((activity, index) => (
            <div key={index} className="flex items-center gap-4 p-3 rounded-lg bg-gray-800/50 border border-gray-700/50 hover:border-gray-600/50 transition-colors">
              <Avatar className="size-10 border-2 border-gray-700">
                <AvatarImage src={activity.avatar} />
                <AvatarFallback className="bg-gradient-to-br from-cyan-500 to-purple-500 text-white font-mono">
                  {activity.initials}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-mono">
                  <span className="font-medium text-emerald-400">{activity.user}</span>{" "}
                  <span className="text-gray-400">{activity.action}</span>
                  {activity.orderId && (
                    <span className="text-cyan-400 font-medium ml-1">
                      {activity.orderId}
                    </span>
                  )}
                </p>
                <p className="text-xs text-gray-600 font-mono">{activity.time}</p>
              </div>
              <Badge
                variant={
                  activity.status === "success"
                    ? "default"
                    : activity.status === "warning"
                    ? "destructive"
                    : "secondary"
                }
                className={`shrink-0 font-mono ${
                  activity.status === "success" 
                    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                    : activity.status === "warning"
                    ? "bg-red-500/10 text-red-400 border-red-500/20"
                    : "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                }`}
              >
                {activity.status}
              </Badge>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}