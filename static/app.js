const $ = (id) => document.getElementById(id);
let students = [];
let selectedId = null;

const today = new Date();
$("recordDate").value =
  `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-${String(today.getDate()).padStart(2,"0")}`;
$("todayDate").textContent = today.toLocaleDateString("id-ID", {
  day:"numeric", month:"short", year:"numeric"
});

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {"Content-Type":"application/json", ...(options.headers || {})}
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Permintaan gagal");
  return data;
}

async function loadStudents() {
  const data = await api("/api/students");
  students = data.students;
  $("studentCount").textContent = students.length;
  $("recordCount").textContent = data.total_records;
  $("todayCount").textContent = data.today_records;

  const map = $("seatMap");
  map.style.gridTemplateColumns =
    `repeat(${Number($("columnCount").value)}, minmax(0, 1fr))`;
  map.replaceChildren();

  const query = $("studentSearch").value.trim().toLocaleLowerCase("id");
  const visibleStudents = students.filter(student =>
    student.name.toLocaleLowerCase("id").includes(query)
  );

  for (const student of visibleStudents) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "seat";
    button.dataset.id = student.id;
    if (student.record_count) button.classList.add("has-records");
    if (student.id === selectedId) button.classList.add("selected");

    const chair = document.createElement("span");
    chair.className = "chair";
    chair.textContent = "♙";

    const name = document.createElement("span");
    name.className = "seat-name";
    name.textContent = student.name;

    button.append(chair, name);

    if (student.record_count) {
      const count = document.createElement("span");
      count.className = "seat-count";
      count.textContent = `${student.record_count} catatan`;
      button.append(count);
    }

    button.draggable = true;
    button.title = "Klik untuk melihat profil. Seret ke kursi lain untuk bertukar posisi.";

    button.addEventListener("click", () => selectStudent(student.id));

    button.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", String(student.id));
      event.dataTransfer.effectAllowed = "move";
    });

    button.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });

    button.addEventListener("drop", async (event) => {
      event.preventDefault();
      const firstId = Number(event.dataTransfer.getData("text/plain"));
      const secondId = student.id;
      if (!firstId || firstId === secondId) return;

      try {
        await api("/api/seat/swap", {
          method: "POST",
          body: JSON.stringify({
            first_id: firstId,
            second_id: secondId
          })
        });
        await loadStudents();
        if (selectedId) await selectStudent(selectedId);
        $("layoutMessage").textContent = "Posisi kursi berhasil ditukar.";
      } catch (error) {
        alert("Gagal memindahkan kursi: " + error.message);
      }
    });

    map.append(button);
  }
}

async function selectStudent(id) {
  selectedId = id;
  const data = await api(`/api/students/${id}/records`);
  const student = data.student;

  $("studentName").textContent = student.name;
  $("studentMeta").textContent =
    `Baris ${student.seat_row}, kursi ${student.seat_col}`;
  $("editNameBtn").hidden = false;
  $("recordForm").hidden = false;
  $("formMessage").textContent = "";
  document.querySelectorAll(".seat").forEach((seat) => {
    seat.classList.toggle("selected", Number(seat.dataset.id) === id);
  });

  const history = $("history");
  history.replaceChildren();
  $("historyCount").textContent = data.records.length;

  if (!data.records.length) {
    history.className = "history empty";
    history.textContent = "Belum ada catatan untuk siswa ini.";
    return;
  }

  history.className = "history";
  for (const record of data.records) {
    const card = document.createElement("article");
    card.className = "record";

    const title = document.createElement("div");
    title.className = "record-title";
    title.textContent = record.game;

    const date = document.createElement("div");
    date.className = "record-date";
    date.textContent = record.record_date;

    card.append(title, date);

    const statusLabel = document.createElement("label");
    statusLabel.className = "followup-label";
    statusLabel.textContent = "Tindak lanjut";

    const statusSelect = document.createElement("select");
    statusSelect.className = "followup-status";
    for (const value of [
      "Belum ditindaklanjuti",
      "Dalam proses",
      "Selesai"
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      statusSelect.append(option);
    }
    statusSelect.value = record.followup_status || "Belum ditindaklanjuti";
    statusSelect.addEventListener("change", async () => {
      statusSelect.disabled = true;
      try {
        await api(`/api/records/${record.id}/status`, {
          method: "PATCH",
          body: JSON.stringify({status: statusSelect.value})
        });
        await loadAuditLog();
      } catch (error) {
        alert("Status gagal diperbarui: " + error.message);
        statusSelect.value = record.followup_status || "Belum ditindaklanjuti";
      } finally {
        statusSelect.disabled = false;
      }
    });
    card.append(statusLabel, statusSelect);



    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "delete-record";
    deleteButton.textContent = "Hapus catatan";
    deleteButton.addEventListener("click", async () => {
      if (!confirm("Hapus catatan ini secara permanen?")) return;
      deleteButton.disabled = true;
      try {
        await api(`/api/records/${record.id}`, {method: "DELETE"});
        await loadStudents();
        await selectStudent(selectedId);
      } catch (error) {
        alert("Gagal menghapus catatan: " + error.message);
        deleteButton.disabled = false;
      }
    });
    card.append(deleteButton);

    if (record.note) {
      const note = document.createElement("div");
      note.className = "record-note";
      note.textContent = record.note;
      card.append(note);
    }
    history.append(card);
  }
}

$("saveRecord").addEventListener("click", async () => {
  if (!selectedId) return;
  $("saveRecord").disabled = true;
  $("formMessage").textContent = "";

  try {
    await api("/api/records", {
      method:"POST",
      body:JSON.stringify({
        student_id:selectedId,
        game:$("game").value,
        note:$("note").value,
        record_date:$("recordDate").value
      })
    });
    $("game").value = "";
    $("note").value = "";
    $("formMessage").textContent = "Catatan berhasil disimpan.";
    await loadStudents();
    await selectStudent(selectedId);
  } catch (error) {
    $("formMessage").textContent = error.message;
  } finally {
    $("saveRecord").disabled = false;
  }
});


$("editNameBtn").addEventListener("click", async () => {
  if (!selectedId) return;

  const student = students.find(s => s.id === selectedId);
  if (!student) return;

  const name = prompt("Masukkan nama baru:", student.name);
  if (name === null || !name.trim()) return;

  try {
    await api(`/api/students/${selectedId}`, {
      method: "PUT",
      body: JSON.stringify({name: name.trim()})
    });

    await loadStudents();
    await selectStudent(selectedId);
    $("formMessage").textContent = "Nama siswa berhasil diperbarui.";
  } catch (error) {
    alert("Gagal mengubah nama: " + error.message);
  }
});

$("applyLayout").addEventListener("click", async () => {
  const columns = Number($("columnCount").value);
  $("applyLayout").disabled = true;
  $("layoutMessage").textContent = "";

  try {
    const result = await api("/api/layout", {
      method: "POST",
      body: JSON.stringify({columns})
    });

    await loadStudents();

    $("layoutMessage").textContent =
      `Denah diperbarui: ${result.rows} baris × ${columns} kolom.`;

    if (selectedId) await selectStudent(selectedId);
  } catch (error) {
    $("layoutMessage").textContent = error.message;
  } finally {
    $("applyLayout").disabled = false;
  }
});


$("studentSearch").addEventListener("input", () => {
  loadStudents().catch(error => {
    $("layoutMessage").textContent = error.message;
  });
});

$("addStudentBtn").addEventListener("click", async () => {
  const name = prompt("Masukkan nama siswa:");
  if (!name || !name.trim()) return;

  try {
    await api("/api/students", {
      method:"POST",
      body:JSON.stringify({name:name.trim()})
    });
    await loadStudents();
  } catch (error) {
    alert("Gagal menambahkan siswa: " + error.message);
  }
});

loadStudents().catch((error) => {
  alert("Gagal memuat data: " + error.message);
});


// Analytics dashboard: reads aggregated data from /api/stats.
const chartInstances = {};

function makeChart(id, config) {
  const canvas = $(id);
  if (!canvas || !window.Chart) return;

  if (chartInstances[id]) chartInstances[id].destroy();
  chartInstances[id] = new Chart(canvas, config);
}

async function loadAnalytics() {
  const message = $("chartMessage");
  if (!window.Chart) {
    message.textContent =
      "Grafik belum termuat. Periksa koneksi internet lalu refresh halaman.";
    return;
  }

  message.textContent = "Memuat statistik...";
  const days = Number($("chartPeriod").value);

  try {
    const data = await api(`/api/stats?days=${days}`);

    $("periodTotal").textContent = data.total;
    $("affectedTotal").textContent = data.affected_students;

    const dateLabels = data.trend.labels.map(value => {
      const parts = value.split("-");
      return `${parts[2]}/${parts[1]}`;
    });

    makeChart("trendChart", {
      type: "line",
      data: {
        labels: dateLabels,
        datasets: [{
          label: "Jumlah catatan",
          data: data.trend.values,
          borderColor: "#3678d4",
          backgroundColor: "rgba(54,120,212,0.12)",
          fill: true,
          tension: 0.3,
          pointRadius: 3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });

    makeChart("gameChart", {
      type: "doughnut",
      data: {
        labels: data.games.labels.length ? data.games.labels : ["Belum ada data"],
        datasets: [{
          data: data.games.values.length ? data.games.values : [1],
          backgroundColor: [
            "#3977c5", "#58a69a", "#e5b45c", "#9b83cc",
            "#df8877", "#7894b5", "#7ebd88", "#b7a2a0"
          ],
          borderWidth: 2,
          borderColor: "#ffffff"
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom" }
        }
      }
    });

    makeChart("studentChart", {
      type: "bar",
      data: {
        labels: data.students.labels.length
          ? data.students.labels : ["Belum ada data"],
        datasets: [{
          label: "Jumlah catatan",
          data: data.students.values.length ? data.students.values : [0],
          backgroundColor: "#6397db",
          borderRadius: 5
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });

    $("studentChart").parentElement.style.height =
      `${Math.max(190, data.students.labels.length * 34)}px`;

    message.textContent =
      `Periode ${data.start} sampai ${data.end}. Statistik berdasarkan catatan yang tersimpan.`;
  } catch (error) {
    message.textContent = "Gagal memuat grafik: " + error.message;
  }
}

if ($("chartPeriod")) {
  $("chartPeriod").addEventListener("change", loadAnalytics);
  loadAnalytics();
}


/* CLASSLOG_UPGRADE_V1 */
async function loadAuditLog() {
  const container = document.getElementById("auditList");
  if (!container) return;
  try {
    const data = await api("/api/audit");
    container.replaceChildren();
    if (!data.items.length) {
      container.textContent = "Belum ada aktivitas yang tercatat.";
      return;
    }
    for (const item of data.items) {
      const row = document.createElement("article");
      row.className = "audit-item";

      const heading = document.createElement("strong");
      heading.textContent = `${item.action} · ${item.student_name}`;

      const details = document.createElement("p");
      details.textContent = item.details || "Tidak ada detail tambahan.";

      const time = document.createElement("time");
      time.textContent = item.created_at;

      row.append(heading, details, time);
      container.append(row);
    }
  } catch (error) {
    container.textContent = "Log aktivitas gagal dimuat: " + error.message;
  }
}

loadAuditLog();
