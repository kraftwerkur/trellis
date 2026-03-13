/**
 * Centralized recharts re-exports.
 * All pages import from here to ensure Turbopack creates a single shared chunk.
 */
export {
  AreaChart,
  AreaChart as RechartsAreaChart,
  Area,
  BarChart,
  Bar,
  CartesianGrid,
  Cell,
  PieChart,
  Pie,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
