import React, { useState } from "react";
import { Tabs, Tab, Box, Paper, CssBaseline } from "@mui/material";
import { useApp } from "./state/store.jsx";
import { selectGateSatisfied } from "./state/selectors.js";
import { Networking } from "./pages/Networking/index.jsx";
import { Toast } from "./components";
import { TablesMapping } from "./pages/TablesMapping/index.jsx";
import { LoggingSchedules } from "./pages/LoggingSchedules/index.jsx";

function a11yProps(name) {
  return {
    id: `tab-${name}`,
    "aria-controls": `panel-${name}`,
  };
}

function TabPanel({ current, name, children, labelledBy }) {
  const isActive = current === name;
  return (
    <div
      role="tabpanel"
      id={`panel-${name}`}
      aria-labelledby={labelledBy || `tab-${name}`}
      hidden={!isActive}
    >
      {isActive && <Box sx={{ p: 2 }}>{children}</Box>}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("networking");
  const { state } = useApp();
  const gateOK = selectGateSatisfied(state);

  return (
    <Box
      sx={{
        fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        p: 2,
      }}
    >
      <Toast />
      <CssBaseline />
      <Box sx={{ mb: 1.5, typography: "h5" }}>Neuract Logger</Box>

      {/* Tabs header */}
      <Paper
        elevation={0}
        variant="outlined"
        sx={{
          borderRadius: 2,
          overflow: "hidden",
          borderColor: "divider",
        }}
      >
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          aria-label="Sections"
          variant="fullWidth"
          textColor="primary"
          indicatorColor="primary"
          TabIndicatorProps={{
            sx: {
              height: 3,
              borderRadius: 3,
            },
          }}
          sx={{
            ".MuiTab-root": {
              textTransform: "none",
              fontWeight: 600,
              minHeight: 44,
            },
          }}
        >
          <Tab
            label="Networking"
            value="networking"
            {...a11yProps("networking")}
          />
          <Tab
            label="Tables & Mapping"
            value="tables"
            disabled={!gateOK}
            {...a11yProps("tables")}
          />
          <Tab
            label="Logging & Schedules"
            value="logging"
            disabled={!gateOK}
            {...a11yProps("logging")}
          />
        </Tabs>

        {/* Panels container with subtle border */}
        <Box
          sx={{
            borderTop: "1px solid",
            borderColor: "divider",
            bgcolor: "background.paper",
          }}
        >
          <TabPanel current={tab} name="networking">
            <Networking onProceed={() => setTab("tables")} />
          </TabPanel>

          <TabPanel current={tab} name="tables">
            <TablesMapping onProceed={() => setTab("logging")} />
          </TabPanel>

          <TabPanel current={tab} name="logging">
            <LoggingSchedules />
          </TabPanel>
        </Box>
      </Paper>
    </Box>
  );
}
