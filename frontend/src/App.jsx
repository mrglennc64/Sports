import { Routes, Route } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Research from "./pages/Research.jsx";
import Calibration from "./pages/Calibration.jsx";
import Clv from "./pages/Clv.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/landing" element={<Landing />} />
      <Route path="/research" element={<Research />} />
      <Route path="/calibration" element={<Calibration />} />
      <Route path="/clv" element={<Clv />} />
    </Routes>
  );
}
