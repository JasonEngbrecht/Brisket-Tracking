"use strict";

const form = document.getElementById("form");
const goBtn = document.getElementById("go");
const clearBtn = document.getElementById("clear");
const errorEl = document.getElementById("error");
const resultsEl = document.getElementById("results");
let chart = null;

clearBtn.addEventListener("click", () => {
  document.getElementById("csv_text").value = "";
  document.getElementById("csv_file").value = "";
  errorEl.textContent = "";
  resultsEl.style.display = "none";
  if (chart) {
    chart.destroy();
    chart = null;
  }
  document.getElementById("csv_text").focus();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.textContent = "";

  const text = document.getElementById("csv_text").value.trim();
  const fileInput = document.getElementById("csv_file");
  const hasFile = fileInput.files && fileInput.files.length > 0;

  if (!text && !hasFile) {
    errorEl.textContent = "Paste the CHEF iQ data or choose a CSV file first.";
    return;
  }

  const data = new FormData();
  if (text) data.append("csv_text", text);
  if (hasFile) data.append("csv_file", fileInput.files[0]);

  goBtn.disabled = true;
  goBtn.textContent = "Analyzing…";
  try {
    const resp = await fetch("/analyze", { method: "POST", body: data });
    const payload = await resp.json();
    if (!payload.ok) {
      errorEl.textContent = payload.error || "Could not process that data.";
      return;
    }
    render(payload);
  } catch (err) {
    errorEl.textContent = "Network error: " + err.message;
  } finally {
    goBtn.disabled = false;
    goBtn.textContent = "Analyze";
  }
});

function render(p) {
  document.getElementById("percent").textContent = p.total_percent.toFixed(1) + "%";
  document.getElementById("texture").textContent = p.texture;
  document.getElementById("duration").textContent = p.duration;
  document.getElementById("peak").textContent = p.peak_internal_f.toFixed(1) + " °F";
  document.getElementById("samples").textContent = p.n_samples;
  resultsEl.style.display = "block";
  drawChart(p.series);
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

function drawChart(series) {
  const labels = series.elapsed_h.map((h) => h);
  const ideal = series.elapsed_h.map(() => 100);
  const ctx = document.getElementById("chart").getContext("2d");
  if (chart) chart.destroy();

  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "% done",
          data: series.cum_percent,
          yAxisID: "y1",
          borderColor: "#d9534f",
          backgroundColor: "rgba(217,83,79,0.12)",
          borderWidth: 2.4,
          pointRadius: 0,
          fill: true,
          tension: 0.2,
        },
        {
          label: "Internal °F",
          data: series.internal_temp_f,
          yAxisID: "y",
          borderColor: "#4a9fd4",
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.2,
        },
        {
          label: "Ideal (100%)",
          data: ideal,
          yAxisID: "y1",
          borderColor: "#5cb85c",
          borderWidth: 1,
          borderDash: [6, 5],
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "linear",
          title: { display: true, text: "Elapsed time (hours)", color: "#b3a59d" },
          ticks: { color: "#b3a59d", maxTicksLimit: 8, callback: (v) => Number(v).toFixed(1) },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
        y: {
          position: "left",
          title: { display: true, text: "Internal °F", color: "#4a9fd4" },
          ticks: { color: "#4a9fd4" },
          grid: { display: false },
        },
        y1: {
          position: "right",
          title: { display: true, text: "% done", color: "#d9534f" },
          ticks: { color: "#d9534f" },
          grid: { color: "rgba(255,255,255,0.06)" },
          beginAtZero: true,
        },
      },
      plugins: {
        legend: { labels: { color: "#f3ece8", boxWidth: 14 } },
        tooltip: {
          callbacks: {
            title: (items) => "t = " + Number(items[0].parsed.x).toFixed(2) + " h",
          },
        },
      },
    },
  });
}
