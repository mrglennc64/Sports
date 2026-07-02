import { Routes, Route } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Landing from "./pages/Landing.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Research from "./pages/Research.jsx";
import Calibration from "./pages/Calibration.jsx";
import Clv from "./pages/Clv.jsx";
import Hedge from "./pages/Hedge.jsx";

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/landing" element={<Landing />} />
        <Route path="/research" element={<Research />} />
        <Route path="/calibration" element={<Calibration />} />
        <Route path="/clv" element={<Clv />} />
        <Route path="/hedge" element={<Hedge />} />
      </Routes>
    </ErrorBoundary>
  );
}
