import csv
import io
import os
from collections import Counter

import boto3
from flask import (
    Flask,
    render_template_string,
    url_for,
    request,
    redirect,
    session
)


app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "cloudmart-dashboard-secret"
)

s3 = boto3.client("s3")

ssm = boto3.client("ssm")

ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)

ADMIN_TOKEN_PARAMETER = os.environ.get(
    "ADMIN_TOKEN_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/auth/admin-token"
)

def get_admin_token():
    response = ssm.get_parameter(
        Name=ADMIN_TOKEN_PARAMETER,
        WithDecryption=True
    )
    return response["Parameter"]["Value"]


REPORT_BUCKET = os.environ.get(
    "REPORT_BUCKET",
    "cloudmart-dev-reports-790574019399"
)

REPORT_PREFIX = os.environ.get(
    "REPORT_PREFIX",
    "reports/"
)

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CloudMart Login</title>
    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #f5f7fb;
            font-family: Arial, sans-serif;
        }

        .login-card {
            width: 360px;
            padding: 32px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
        }

        .brand {
            text-align: center;
            margin-bottom: 24px;
        }

        .brand h1 {
            margin: 0 0 6px;
            font-size: 28px;
        }

        .brand p {
            margin: 0;
            color: #667085;
        }

        label {
            display: block;
            margin: 14px 0 6px;
            font-weight: 600;
        }

        input {
            width: 100%;
            padding: 11px 12px;
            border: 1px solid #d0d5dd;
            border-radius: 6px;
            font-size: 14px;
        }

        button {
            width: 100%;
            margin-top: 22px;
            padding: 12px;
            border: 0;
            border-radius: 6px;
            background: #1d4ed8;
            color: white;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
        }

        .error {
            margin-bottom: 16px;
            padding: 10px;
            border-radius: 6px;
            background: #fef2f2;
            color: #b42318;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <div class="brand">
            <h1>CloudMart</h1>
            <p>Operations Dashboard</p>
        </div>

        {% if error %}
            <div class="error">{{ error }}</div>
        {% endif %}

        <form method="POST" action="{{ url_for('login') }}">
            <label for="username">Username</label>
            <input
                type="text"
                id="username"
                name="username"
                autocomplete="username"
                required
            >

            <label for="password">Password</label>
            <input
                type="password"
                id="password"
                name="password"
                autocomplete="current-password"
                required
            >

            <button type="submit">Sign In</button>
        </form>
    </div>
</body>
</html>
"""

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>CloudMart Operations Dashboard</title>

    <style>
        :root {
            --bg: #f1f5f9;
            --surface: #ffffff;
            --surface-soft: #f8fafc;
            --border: #e2e8f0;
            --text: #0f172a;
            --muted: #64748b;
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --success: #16a34a;
            --warning: #d97706;
            --danger: #dc2626;
            --sidebar: #0f172a;
            --sidebar-soft: #1e293b;
            --shadow: 0 8px 30px rgba(15, 23, 42, 0.07);
            --radius: 16px;
        }

        * {
            box-sizing: border-box;
        }

        html {
            scroll-behavior: smooth;
        }

        body {
            margin: 0;
            font-family:
                Inter,
                ui-sans-serif,
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                sans-serif;
            background: var(--bg);
            color: var(--text);
        }

        button,
        input,
        select {
            font: inherit;
        }

        a {
            text-decoration: none;
        }

        .app {
            min-height: 100vh;
            display: flex;
        }

        /* =========================
           SIDEBAR
           ========================= */

        .sidebar {
            width: 245px;
            min-height: 100vh;
            background: var(--sidebar);
            color: white;
            position: fixed;
            left: 0;
            top: 0;
            bottom: 0;
            z-index: 100;
            display: flex;
            flex-direction: column;
            padding: 22px 16px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 10px 26px;
        }

        .brand-icon {
            width: 42px;
            height: 42px;
            border-radius: 12px;
            background: linear-gradient(135deg, #3b82f6, #6366f1);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 21px;
            font-weight: 800;
            box-shadow: 0 8px 20px rgba(37, 99, 235, 0.35);
        }

        .brand-name {
            font-size: 18px;
            font-weight: 800;
            letter-spacing: -0.3px;
        }

        .brand-subtitle {
            font-size: 11px;
            color: #94a3b8;
            margin-top: 2px;
        }

        .nav-label {
            padding: 10px 12px 8px;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
            font-weight: 700;
        }

        .nav {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .nav-link {
            display: flex;
            align-items: center;
            gap: 12px;
            color: #cbd5e1;
            padding: 11px 12px;
            border-radius: 10px;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s ease;
        }

        .nav-link:hover,
        .nav-link.active {
            background: var(--sidebar-soft);
            color: white;
        }

        .nav-icon {
            width: 21px;
            text-align: center;
            font-size: 15px;
        }

        .sidebar-bottom {
            margin-top: auto;
            padding: 14px 10px 4px;
        }

        .system-status {
            border: 1px solid #334155;
            background: rgba(30, 41, 59, 0.7);
            border-radius: 13px;
            padding: 13px;
        }

        .system-status-title {
            font-size: 11px;
            color: #94a3b8;
            margin-bottom: 7px;
        }

        .status-online {
            display: flex;
            align-items: center;
            gap: 7px;
            font-size: 12px;
            font-weight: 700;
        }

        .online-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.12);
        }

        /* =========================
           MAIN
           ========================= */

        .main {
            margin-left: 245px;
            width: calc(100% - 245px);
            min-width: 0;
        }

        .topbar {
            height: 76px;
            background: rgba(255, 255, 255, 0.94);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 34px;
            position: sticky;
            top: 0;
            z-index: 50;
            backdrop-filter: blur(12px);
        }

        .page-title {
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.4px;
        }

        .page-subtitle {
            margin-top: 3px;
            color: var(--muted);
            font-size: 12px;
        }

        .topbar-right {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .environment {
            display: flex;
            align-items: center;
            gap: 7px;
            background: #ecfdf5;
            color: #047857;
            border: 1px solid #bbf7d0;
            padding: 8px 13px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }

        .environment-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #10b981;
        }

        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 30px 34px 55px;
        }

        /* =========================
           HERO
           ========================= */

        .hero {
            background:
                radial-gradient(
                    circle at 85% 20%,
                    rgba(96, 165, 250, 0.25),
                    transparent 32%
                ),
                linear-gradient(135deg, #172554, #1e3a8a 52%, #2563eb);
            border-radius: 20px;
            color: white;
            padding: 28px 30px;
            margin-bottom: 25px;
            box-shadow: 0 14px 40px rgba(37, 99, 235, 0.18);
            position: relative;
            overflow: hidden;
        }

        .hero::after {
            content: "";
            position: absolute;
            width: 230px;
            height: 230px;
            right: -90px;
            top: -100px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 50%;
        }

        .hero-content {
            position: relative;
            z-index: 2;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 25px;
            flex-wrap: wrap;
        }

        .hero-kicker {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1.4px;
            color: #bfdbfe;
            font-weight: 800;
            margin-bottom: 8px;
        }

        .hero h1 {
            margin: 0;
            font-size: 27px;
            letter-spacing: -0.8px;
        }

        .hero p {
            margin: 8px 0 0;
            color: #dbeafe;
            font-size: 13px;
            max-width: 650px;
        }

        .hero-actions {
            display: flex;
            gap: 9px;
            flex-wrap: wrap;
        }

        /* =========================
           BUTTONS
           ========================= */

        .button {
            border: none;
            border-radius: 10px;
            padding: 10px 15px;
            font-size: 12px;
            font-weight: 750;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 7px;
            transition:
                transform 0.18s ease,
                box-shadow 0.18s ease,
                background 0.18s ease;
        }

        .button:hover {
            transform: translateY(-1px);
        }

        .button-primary {
            background: var(--primary);
            color: white;
            box-shadow: 0 5px 15px rgba(37, 99, 235, 0.2);
        }

        .button-primary:hover {
            background: var(--primary-dark);
        }

        .button-light {
            background: white;
            color: #1e3a8a;
        }

        .button-light:hover {
            background: #eff6ff;
        }

        .button-secondary {
            background: #f1f5f9;
            color: #334155;
            border: 1px solid var(--border);
        }

        .button-secondary:hover {
            background: #e2e8f0;
        }

        .button-small {
            padding: 7px 10px;
            font-size: 11px;
            border-radius: 8px;
        }

        /* =========================
           ERROR
           ========================= */

        .error {
            background: #fff1f2;
            border: 1px solid #fecdd3;
            color: #9f1239;
            padding: 18px;
            border-radius: 14px;
            margin-bottom: 25px;
        }

        .error-title {
            font-weight: 800;
            margin-bottom: 5px;
        }

        .error-detail {
            font-size: 13px;
        }

        /* =========================
           KPI
           ========================= */

        .section-heading {
            margin: 0 0 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .section-heading h2 {
            margin: 0;
            font-size: 16px;
            letter-spacing: -0.2px;
        }

        .section-heading span {
            color: var(--muted);
            font-size: 11px;
        }

        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 28px;
        }

        .kpi-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            box-shadow: var(--shadow);
            transition:
                transform 0.2s ease,
                box-shadow 0.2s ease;
            position: relative;
            overflow: hidden;
        }

        .kpi-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 13px 35px rgba(15, 23, 42, 0.10);
        }

        .kpi-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .kpi-label {
            color: var(--muted);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            font-weight: 800;
        }

        .kpi-icon {
            width: 37px;
            height: 37px;
            border-radius: 11px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }

        .icon-blue {
            background: #eff6ff;
            color: #2563eb;
        }

        .icon-orange {
            background: #fff7ed;
            color: #ea580c;
        }

        .icon-purple {
            background: #f5f3ff;
            color: #7c3aed;
        }

        .icon-green {
            background: #ecfdf5;
            color: #059669;
        }

        .kpi-value {
            margin-top: 17px;
            font-size: 30px;
            line-height: 1;
            font-weight: 850;
            letter-spacing: -1px;
        }

        .kpi-note {
            margin-top: 9px;
            color: #94a3b8;
            font-size: 11px;
        }

        /* =========================
           GRID / CARDS
           ========================= */

        .dashboard-grid {
            display: grid;
            grid-template-columns: 1.35fr 1fr;
            gap: 20px;
            margin-bottom: 22px;
        }

        .panel {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            padding: 22px;
            min-width: 0;
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 15px;
            margin-bottom: 18px;
        }

        .panel-title {
            font-size: 16px;
            font-weight: 800;
        }

        .panel-description {
            color: var(--muted);
            font-size: 11px;
            margin-top: 4px;
        }

        /* =========================
           STATUS
           ========================= */

        .status-list {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 11px;
        }

        .status-item {
            border: 1px solid var(--border);
            background: var(--surface-soft);
            border-radius: 12px;
            padding: 15px;
            transition: all 0.2s ease;
        }

        .status-item:hover {
            transform: translateY(-1px);
            border-color: #cbd5e1;
        }

        .status-item-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }

        .status-name {
            font-size: 11px;
            font-weight: 800;
            color: #475569;
        }

        .status-count {
            font-size: 23px;
            font-weight: 850;
            margin-top: 8px;
        }

        .status-bar {
            height: 5px;
            background: #e2e8f0;
            border-radius: 99px;
            margin-top: 12px;
            overflow: hidden;
        }

        .status-bar-fill {
            height: 100%;
            border-radius: inherit;
            min-width: 3px;
        }

        .bar-success {
            background: #22c55e;
        }

        .bar-warning {
            background: #f59e0b;
        }

        .bar-danger {
            background: #ef4444;
        }

        .bar-neutral {
            background: #94a3b8;
        }

        /* =========================
           REPORT SUMMARY
           ========================= */

        .report-summary {
            display: grid;
            gap: 10px;
        }

        .summary-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 15px;
            padding: 11px 13px;
            background: var(--surface-soft);
            border: 1px solid var(--border);
            border-radius: 10px;
        }

        .summary-label {
            color: var(--muted);
            font-size: 11px;
            font-weight: 700;
        }

        .summary-value {
            font-size: 12px;
            font-weight: 750;
            text-align: right;
            word-break: break-word;
        }

        /* =========================
           SECTION
           ========================= */

        .section {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            box-shadow: var(--shadow);
            padding: 22px;
            margin-bottom: 22px;
            scroll-margin-top: 95px;
        }

        /* =========================
           SEARCH / FILTER
           ========================= */

        .toolbar {
            display: flex;
            align-items: center;
            gap: 9px;
            flex-wrap: wrap;
        }

        .search-box {
            position: relative;
        }

        .search-box input {
            width: 230px;
            border: 1px solid var(--border);
            background: #f8fafc;
            border-radius: 9px;
            padding: 9px 12px 9px 34px;
            outline: none;
            font-size: 12px;
            color: var(--text);
            transition: all 0.2s ease;
        }

        .search-box input:focus {
            background: white;
            border-color: #93c5fd;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.10);
        }

        .search-icon {
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: #94a3b8;
            font-size: 12px;
        }

        .filter-select {
            border: 1px solid var(--border);
            background: #f8fafc;
            border-radius: 9px;
            padding: 9px 12px;
            font-size: 12px;
            color: #475569;
            outline: none;
        }

        /* =========================
           TABLE
           ========================= */

        .table-wrapper {
            overflow-x: auto;
            border: 1px solid var(--border);
            border-radius: 12px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 850px;
        }

        th {
            background: #f8fafc;
            color: #64748b;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.65px;
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
        }

        td {
            padding: 13px 14px;
            border-bottom: 1px solid #f1f5f9;
            font-size: 12px;
            color: #334155;
            vertical-align: middle;
        }

        tbody tr {
            transition: background 0.15s ease;
        }

        tbody tr:hover td {
            background: #f8fafc;
        }

        tbody tr:last-child td {
            border-bottom: none;
        }

        .product-name {
            font-weight: 750;
            color: #1e293b;
        }

        .product-id,
        .order-id {
            font-weight: 750;
            color: #2563eb;
        }

        .price {
            font-weight: 700;
            color: #0f172a;
        }

        .stock-number {
            font-weight: 850;
        }

        .stock-cell {
            min-width: 120px;
        }

        .stock-progress {
            width: 100%;
            height: 5px;
            background: #e2e8f0;
            border-radius: 99px;
            overflow: hidden;
            margin-top: 6px;
        }

        .stock-progress-fill {
            height: 100%;
            border-radius: inherit;
            background: #22c55e;
        }

        .stock-progress-fill.low {
            background: #f59e0b;
        }

        .low-stock-row td {
            background: #fffaf0;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 5px 9px;
            border-radius: 999px;
            font-size: 10px;
            font-weight: 800;
            white-space: nowrap;
        }

        .badge-success {
            background: #dcfce7;
            color: #166534;
        }

        .badge-warning {
            background: #fef3c7;
            color: #92400e;
        }

        .badge-danger {
            background: #fee2e2;
            color: #991b1b;
        }

        .badge-neutral {
            background: #e2e8f0;
            color: #475569;
        }

        .badge-dot {
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: currentColor;
        }

        /* =========================
           REPORTS
           ========================= */

        .reports-list {
            display: grid;
            gap: 10px;
        }

        .previous-report {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            padding: 15px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: var(--surface-soft);
            transition: all 0.2s ease;
        }

        .previous-report:hover {
            background: white;
            border-color: #cbd5e1;
            box-shadow: 0 5px 18px rgba(15, 23, 42, 0.05);
        }

        .report-file {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }

        .file-icon {
            width: 38px;
            height: 38px;
            flex-shrink: 0;
            border-radius: 10px;
            background: #eff6ff;
            color: #2563eb;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 16px;
        }

        .previous-report-name {
            font-weight: 750;
            font-size: 12px;
            color: #334155;
            word-break: break-word;
        }

        .previous-report-date {
            font-size: 10px;
            color: #94a3b8;
            margin-top: 4px;
        }

        .previous-report-actions {
            display: flex;
            gap: 7px;
            flex-shrink: 0;
        }

        /* =========================
           EMPTY
           ========================= */

        .empty {
            padding: 42px 20px;
            text-align: center;
            color: #94a3b8;
            font-size: 12px;
            background: #f8fafc;
            border: 1px dashed #cbd5e1;
            border-radius: 12px;
        }

        .empty-icon {
            font-size: 28px;
            margin-bottom: 8px;
        }

        /* =========================
           MODAL
           ========================= */

        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            inset: 0;
            background: rgba(15, 23, 42, 0.68);
            padding: 25px;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(4px);
        }

        .modal.open {
            display: flex;
            animation: fadeIn 0.18s ease;
        }

        .modal-content {
            background: white;
            width: 100%;
            max-width: 1150px;
            max-height: 88vh;
            overflow: hidden;
            border-radius: 18px;
            box-shadow: 0 30px 80px rgba(0, 0, 0, 0.28);
            animation: modalIn 0.2s ease;
            display: flex;
            flex-direction: column;
        }

        .modal-header {
            padding: 18px 22px;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
        }

        .modal-title {
            font-size: 16px;
            font-weight: 800;
        }

        .modal-subtitle {
            color: var(--muted);
            font-size: 10px;
            margin-top: 3px;
        }

        .close {
            width: 32px;
            height: 32px;
            border: none;
            background: #f1f5f9;
            color: #64748b;
            border-radius: 9px;
            font-size: 19px;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .close:hover {
            background: #e2e8f0;
            color: #0f172a;
        }

        .modal-body {
            padding: 20px;
            overflow: auto;
        }

        .csv-preview {
            white-space: pre;
            overflow: auto;
            background: #0f172a;
            color: #dbeafe;
            border-radius: 12px;
            padding: 18px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
            font-size: 11px;
            line-height: 1.6;
            max-height: 62vh;
        }

        /* =========================
           TOAST
           ========================= */

        .toast {
            position: fixed;
            right: 25px;
            bottom: 25px;
            z-index: 2000;
            background: #0f172a;
            color: white;
            padding: 12px 16px;
            border-radius: 11px;
            font-size: 12px;
            font-weight: 650;
            box-shadow: 0 15px 40px rgba(15, 23, 42, 0.22);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.25s ease;
            pointer-events: none;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        /* =========================
           FOOTER
           ========================= */

        .footer {
            text-align: center;
            color: #94a3b8;
            font-size: 10px;
            padding: 5px 0 15px;
        }

        /* =========================
           ANIMATIONS
           ========================= */

        @keyframes fadeIn {
            from {
                opacity: 0;
            }

            to {
                opacity: 1;
            }
        }

        @keyframes modalIn {
            from {
                opacity: 0;
                transform: translateY(10px) scale(0.99);
            }

            to {
                opacity: 1;
                transform: translateY(0) scale(1);
            }
        }

        /* =========================
           MOBILE
           ========================= */

        @media (max-width: 1200px) {

            .kpi-grid {
                grid-template-columns: repeat(2, 1fr);
            }

            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 850px) {

            .sidebar {
                width: 72px;
                padding: 16px 9px;
            }

            .brand {
                justify-content: center;
                padding: 8px 0 24px;
            }

            .brand-text,
            .nav-label,
            .nav-link span:not(.nav-icon),
            .sidebar-bottom {
                display: none;
            }

            .nav-link {
                justify-content: center;
                padding: 12px;
            }

            .main {
                margin-left: 72px;
                width: calc(100% - 72px);
            }

            .topbar {
                padding: 0 20px;
            }

            .container {
                padding: 24px 20px 45px;
            }
        }

        @media (max-width: 620px) {

            .topbar {
                height: auto;
                min-height: 72px;
                padding: 15px;
                gap: 10px;
            }

            .page-subtitle {
                display: none;
            }

            .environment {
                padding: 7px 10px;
                font-size: 10px;
            }

            .container {
                padding: 18px 12px 35px;
            }

            .hero {
                padding: 23px;
            }

            .hero h1 {
                font-size: 22px;
            }

            .hero-actions {
                width: 100%;
            }

            .hero-actions .button {
                flex: 1;
            }

            .kpi-grid {
                grid-template-columns: 1fr;
            }

            .panel,
            .section {
                padding: 17px;
            }

            .status-list {
                grid-template-columns: 1fr;
            }

            .search-box,
            .search-box input {
                width: 100%;
            }

            .toolbar {
                width: 100%;
            }

            .filter-select {
                flex: 1;
            }

            .previous-report {
                align-items: flex-start;
                flex-direction: column;
            }

            .previous-report-actions {
                width: 100%;
            }

            .previous-report-actions .button {
                flex: 1;
            }

            .modal {
                padding: 10px;
            }

            .modal-content {
                max-height: 94vh;
            }
        }
    </style>
</head>

<body>

<div class="app">

    <!-- =========================
         SIDEBAR
         ========================= -->

    <aside class="sidebar">

        <div class="brand">

            <div class="brand-icon">
                C
            </div>

            <div class="brand-text">

                <div class="brand-name">
                    CloudMart
                </div>

                <div class="brand-subtitle">
                    Operations Console
                </div>

            </div>

        </div>


        <div class="nav-label">
            Workspace
        </div>


        <nav class="nav">

            <a class="nav-link active" href="#overview">

                <span class="nav-icon">⌂</span>
                <span>Overview</span>

            </a>


            <a class="nav-link" href="#orders">

                <span class="nav-icon">▣</span>
                <span>Orders</span>

            </a>


            <a class="nav-link" href="#inventory">

                <span class="nav-icon">▤</span>
                <span>Inventory</span>

            </a>


            <a class="nav-link" href="#reports">

                <span class="nav-icon">◫</span>
                <span>Reports</span>

            </a>

        </nav>


        <div class="nav-label">
            System
        </div>


        <nav class="nav">

            <a class="nav-link" href="#overview">

                <span class="nav-icon">◉</span>
                <span>System Status</span>

            </a>

        </nav>

        <nav class="nav">

            <a class="nav-link" href="{{ url_for('logout') }}">

                <span class="nav-icon">↪</span>
                <span>Logout</span>

            </a>

        </nav>


        <div class="sidebar-bottom">

            <div class="system-status">

                <div class="system-status-title">
                    CloudMart Platform
                </div>

                <div class="status-online">

                    <span class="online-dot"></span>

                    <span>Dashboard Online</span>

                </div>

            </div>

        </div>

    </aside>


    <!-- =========================
         MAIN
         ========================= -->

    <main class="main">

        <header class="topbar">

            <div>

                <div class="page-title">
                    Operations Dashboard
                </div>

                <div class="page-subtitle">
                    Monitor orders, inventory and daily reporting
                </div>

            </div>


            <div class="topbar-right">

                <div class="environment">

                    <span class="environment-dot"></span>

                    {{ environment or "Unknown" }}

                </div>

            </div>

        </header>


        <div class="container" id="overview">


            {% if error %}

                <div class="error">

                    <div class="error-title">
                        Unable to load dashboard data
                    </div>

                    <div class="error-detail">
                        {{ error }}
                    </div>

                </div>

            {% else %}


                <!-- =========================
                     HERO
                     ========================= -->

                <section class="hero">

                    <div class="hero-content">

                        <div>

                            <div class="hero-kicker">
                                CloudMart Operations
                            </div>

                            <h1>
                                Daily business overview
                            </h1>

                            <p>
                                Monitor your latest orders, inventory health
                                and generated reports from one place.
                            </p>

                        </div>


                        <div class="hero-actions">

                            <button
                                class="button button-light"
                                onclick="openLatestReport()"
                            >
                                ◉ View Report
                            </button>


                            <a
                                class="button button-primary"
                                href="{{ url_for('download_report') }}"
                                onclick="showToast('Report download started')"
                            >
                                ↓ Download CSV
                            </a>

                        </div>

                    </div>

                </section>


                <!-- =========================
                     KPI CARDS
                     ========================= -->

                <div class="section-heading">

                    <h2>
                        Business Snapshot
                    </h2>

                    <span>
                        Latest report
                    </span>

                </div>


                <div class="kpi-grid">


                    <div class="kpi-card">

                        <div class="kpi-top">

                            <div class="kpi-label">
                                Total Products
                            </div>

                            <div class="kpi-icon icon-blue">
                                ▤
                            </div>

                        </div>

                        <div class="kpi-value">
                            {{ products|length }}
                        </div>

                        <div class="kpi-note">
                            Products in latest report
                        </div>

                    </div>


                    <div class="kpi-card">

                        <div class="kpi-top">

                            <div class="kpi-label">
                                Low Stock
                            </div>

                            <div class="kpi-icon icon-orange">
                                !
                            </div>

                        </div>

                        <div class="kpi-value">
                            {{ low_stock_count }}
                        </div>

                        <div class="kpi-note">
                            Products requiring attention
                        </div>

                    </div>


                    <div class="kpi-card">

                        <div class="kpi-top">

                            <div class="kpi-label">
                                Order Items
                            </div>

                            <div class="kpi-icon icon-purple">
                                #
                            </div>

                        </div>

                        <div class="kpi-value">
                            {{ orders|length }}
                        </div>

                        <div class="kpi-note">
                            Order item records
                        </div>

                    </div>


                    <div class="kpi-card">

                        <div class="kpi-top">

                            <div class="kpi-label">
                                Report Status
                            </div>

                            <div class="kpi-icon icon-green">
                                ✓
                            </div>

                        </div>

                        <div class="kpi-value" style="font-size:24px;">

                            {% if products or orders %}
                                Ready
                            {% else %}
                                Empty
                            {% endif %}

                        </div>

                        <div class="kpi-note">

                            {% if products or orders %}
                                Latest report loaded
                            {% else %}
                                No business records
                            {% endif %}

                        </div>

                    </div>


                </div>


                <!-- =========================
                     SUMMARY GRID
                     ========================= -->

                <div class="dashboard-grid">


                    <!-- ORDER STATUS -->

                    <section class="panel" id="orders">

                        <div class="panel-header">

                            <div>

                                <div class="panel-title">
                                    Order Status
                                </div>

                                <div class="panel-description">
                                    Distribution of orders in the latest report
                                </div>

                            </div>

                        </div>


                        {% set total_orders = orders|length %}


                        <div class="status-list">


                            {% for status in [
                                "COMPLETED",
                                "PENDING",
                                "PROCESSING",
                                "FAILED"
                            ] %}

                                {% set count =
                                    order_status_counts.get(status, 0)
                                %}

                                {% if total_orders > 0 %}

                                    {% set percentage =
                                        ((count / total_orders) * 100)
                                        |round(0)
                                    %}

                                {% else %}

                                    {% set percentage = 0 %}

                                {% endif %}


                                <div class="status-item">

                                    <div class="status-item-top">

                                        <div class="status-name">
                                            {{ status }}
                                        </div>

                                        <div>

                                            {% if status == "COMPLETED" %}

                                                <span class="badge badge-success">
                                                    <span class="badge-dot"></span>
                                                    Healthy
                                                </span>

                                            {% elif status == "FAILED" %}

                                                <span class="badge badge-danger">
                                                    <span class="badge-dot"></span>
                                                    Attention
                                                </span>

                                            {% elif status in ["PENDING", "PROCESSING"] %}

                                                <span class="badge badge-warning">
                                                    <span class="badge-dot"></span>
                                                    Active
                                                </span>

                                            {% else %}

                                                <span class="badge badge-neutral">
                                                    <span class="badge-dot"></span>
                                                    Other
                                                </span>

                                            {% endif %}

                                        </div>

                                    </div>


                                    <div class="status-count">
                                        {{ count }}
                                    </div>


                                    <div class="status-bar">

                                        <div
                                            class="status-bar-fill
                                            {% if status == 'COMPLETED' %}
                                                bar-success
                                            {% elif status == 'FAILED' %}
                                                bar-danger
                                            {% elif status in ['PENDING', 'PROCESSING'] %}
                                                bar-warning
                                            {% else %}
                                                bar-neutral
                                            {% endif %}"
                                            style="width: {{ percentage }}%;"
                                        ></div>

                                    </div>


                                    <div
                                        style="
                                            margin-top:6px;
                                            font-size:10px;
                                            color:#94a3b8;
                                        "
                                    >
                                        {{ percentage }}% of order items
                                    </div>

                                </div>

                            {% endfor %}


                        </div>

                    </section>


                    <!-- REPORT SUMMARY -->

                    <section class="panel">

                        <div class="panel-header">

                            <div>

                                <div class="panel-title">
                                    Latest Report
                                </div>

                                <div class="panel-description">
                                    Report metadata and generation details
                                </div>

                            </div>

                            <span class="badge badge-success">
                                <span class="badge-dot"></span>
                                Available
                            </span>

                        </div>


                        <div class="report-summary">


                            <div class="summary-row">

                                <div class="summary-label">
                                    Report Date
                                </div>

                                <div class="summary-value">
                                    {{ report_date or "N/A" }}
                                </div>

                            </div>


                            <div class="summary-row">

                                <div class="summary-label">
                                    Report Window
                                </div>

                                <div class="summary-value">
                                    {{ report_window or "N/A" }}
                                </div>

                            </div>


                            <div class="summary-row">

                                <div class="summary-label">
                                    Environment
                                </div>

                                <div class="summary-value">
                                    {{ environment or "Unknown" }}
                                </div>

                            </div>


                            <div class="summary-row">

                                <div class="summary-label">
                                    Report File
                                </div>

                                <div class="summary-value">
                                    {{ report_key }}
                                </div>

                            </div>


                        </div>

                    </section>


                </div>


                <!-- =========================
                     INVENTORY
                     ========================= -->

                <section class="section" id="inventory">

                    <div class="panel-header">

                        <div>

                            <div class="panel-title">
                                Inventory Health
                            </div>

                            <div class="panel-description">
                                Current product stock and availability
                            </div>

                        </div>


                        <div class="toolbar">

                            <div class="search-box">

                                <span class="search-icon">
                                    ⌕
                                </span>

                                <input
                                    type="text"
                                    id="productSearch"
                                    placeholder="Search products..."
                                    onkeyup="filterProducts()"
                                >

                            </div>


                            <select
                                id="stockFilter"
                                class="filter-select"
                                onchange="filterProducts()"
                            >

                                <option value="all">
                                    All Stock
                                </option>

                                <option value="low">
                                    Low Stock
                                </option>

                                <option value="normal">
                                    Normal Stock
                                </option>

                            </select>

                        </div>

                    </div>


                    {% if products %}


                        <div class="table-wrapper">

                            <table>

                                <thead>

                                    <tr>

                                        <th>
                                            Product
                                        </th>

                                        <th>
                                            Price
                                        </th>

                                        <th>
                                            Current Stock
                                        </th>

                                        <th>
                                            Product Status
                                        </th>

                                        <th>
                                            Stock Health
                                        </th>

                                    </tr>

                                </thead>


                                <tbody id="productTable">


                                {% for product in products %}


                                    <tr
                                        class="product-row"
                                        data-name="{{ product['Product Name']|lower }}"
                                        data-stock="{% if product['Low Stock'].upper() == 'YES' %}low{% else %}normal{% endif %}"
                                    >


                                        <td>

                                            <div class="product-name">
                                                {{ product["Product Name"] }}
                                            </div>

                                            <div
                                                class="product-id"
                                                style="
                                                    font-size:10px;
                                                    margin-top:4px;
                                                "
                                            >
                                                ID #{{ product["Product ID"] }}
                                            </div>

                                        </td>


                                        <td class="price">
                                            {{ product["Price"] }}
                                        </td>


                                        <td class="stock-cell">

                                            <span class="stock-number">
                                                {{ product["Current Stock"] }}
                                            </span>


                                            {% set stock =
                                                product["Current Stock"]|int
                                            %}

                                            {% set stock_width =
                                                [stock * 5, 100]|min
                                            %}


                                            <div class="stock-progress">

                                                <div
                                                    class="
                                                        stock-progress-fill
                                                        {% if product['Low Stock'].upper() == 'YES' %}
                                                            low
                                                        {% endif %}
                                                    "
                                                    style="
                                                        width:
                                                        {{ stock_width }}%;
                                                    "
                                                ></div>

                                            </div>

                                        </td>


                                        <td>

                                            {% if product["Product Status"].upper() == "ACTIVE" %}

                                                <span class="badge badge-success">

                                                    <span class="badge-dot"></span>

                                                    ACTIVE

                                                </span>

                                            {% else %}

                                                <span class="badge badge-neutral">

                                                    <span class="badge-dot"></span>

                                                    {{ product["Product Status"] }}

                                                </span>

                                            {% endif %}

                                        </td>


                                        <td>

                                            {% if product["Low Stock"].upper() == "YES" %}

                                                <span class="badge badge-warning">

                                                    <span class="badge-dot"></span>

                                                    LOW STOCK

                                                </span>

                                            {% else %}

                                                <span class="badge badge-success">

                                                    <span class="badge-dot"></span>

                                                    NORMAL

                                                </span>

                                            {% endif %}

                                        </td>


                                    </tr>


                                {% endfor %}


                                </tbody>

                            </table>

                        </div>


                        <div
                            id="noProductsFound"
                            class="empty"
                            style="display:none; margin-top:12px;"
                        >

                            <div class="empty-icon">
                                ⌕
                            </div>

                            No products match your search or filter.

                        </div>


                    {% else %}


                        <div class="empty">

                            <div class="empty-icon">
                                ▤
                            </div>

                            No products were present in the latest report.

                        </div>


                    {% endif %}

                </section>


                <!-- =========================
                     ORDER DETAILS
                     ========================= -->

                <section class="section">

                    <div class="panel-header">

                        <div>

                            <div class="panel-title">
                                Recent Order Items
                            </div>

                            <div class="panel-description">
                                Detailed order and product information
                            </div>

                        </div>


                        {% if orders %}

                            <button
                                class="button button-primary"
                                onclick="openOrdersModal()"
                            >
                                ⊞ Detailed View
                            </button>

                        {% endif %}

                    </div>


                    {% if orders %}


                        <div class="table-wrapper">

                            <table>

                                <thead>

                                    <tr>

                                        <th>
                                            Order
                                        </th>

                                        <th>
                                            Customer
                                        </th>

                                        <th>
                                            Created
                                        </th>

                                        <th>
                                            Status
                                        </th>

                                        <th>
                                            Total
                                        </th>

                                        <th>
                                            Product
                                        </th>

                                        <th>
                                            Quantity
                                        </th>

                                        <th>
                                            Subtotal
                                        </th>

                                    </tr>

                                </thead>


                                <tbody>


                                {% for order in orders %}


                                    <tr>


                                        <td>

                                            <div class="order-id">
                                                #{{ order["Order ID"] }}
                                            </div>

                                        </td>


                                        <td>
                                            {{ order["Customer ID"] }}
                                        </td>


                                        <td>
                                            {{ order["Created Time"] }}
                                        </td>


                                        <td>


                                            {% if order["Order Status"].upper() == "COMPLETED" %}

                                                <span class="badge badge-success">
                                                    <span class="badge-dot"></span>
                                                    COMPLETED
                                                </span>


                                            {% elif order["Order Status"].upper() == "FAILED" %}

                                                <span class="badge badge-danger">
                                                    <span class="badge-dot"></span>
                                                    FAILED
                                                </span>


                                            {% elif order["Order Status"].upper() in ["PENDING", "PROCESSING"] %}

                                                <span class="badge badge-warning">
                                                    <span class="badge-dot"></span>
                                                    {{ order["Order Status"] }}
                                                </span>


                                            {% else %}

                                                <span class="badge badge-neutral">
                                                    <span class="badge-dot"></span>
                                                    {{ order["Order Status"] }}
                                                </span>

                                            {% endif %}


                                        </td>


                                        <td class="price">
                                            {{ order["Total Amount"] }}
                                        </td>


                                        <td>
                                            {{ order["Product Name"] }}
                                        </td>


                                        <td>
                                            {{ order["Quantity"] }}
                                        </td>


                                        <td class="price">
                                            {{ order["Subtotal"] }}
                                        </td>


                                    </tr>


                                {% endfor %}


                                </tbody>

                            </table>

                        </div>


                    {% else %}


                        <div class="empty">

                            <div class="empty-icon">
                                ▣
                            </div>

                            No order items were present in the latest report.

                        </div>


                    {% endif %}


                </section>


                <!-- =========================
                     PREVIOUS REPORTS
                     ========================= -->

                <section class="section" id="reports">

                    <div class="panel-header">

                        <div>

                            <div class="panel-title">
                                Report Archive
                            </div>

                            <div class="panel-description">
                                Daily reports currently available in Amazon S3
                            </div>

                        </div>


                        {% if previous_reports %}

                            <span class="badge badge-neutral">

                                {{ previous_reports|length }}
                                reports

                            </span>

                        {% endif %}

                    </div>


                    {% if previous_reports %}


                        <div class="reports-list">


                        {% for report in previous_reports %}


                            <div class="previous-report">


                                <div class="report-file">

                                    <div class="file-icon">
                                        CSV
                                    </div>


                                    <div>

                                        <div class="previous-report-name">
                                            {{ report["name"] }}
                                        </div>

                                        <div class="previous-report-date">
                                            Uploaded:
                                            {{ report["last_modified"] }}
                                        </div>

                                    </div>

                                </div>


                                <div class="previous-report-actions">


                                    <button
                                        class="button button-secondary button-small"
                                        onclick="openPreviousReport(
                                            '{{ url_for(
                                                'view_previous_report',
                                                report_key=report['key']
                                            ) }}',
                                            '{{ report['name']|e }}'
                                        )"
                                    >
                                        View
                                    </button>


                                    <a
                                        class="button button-primary button-small"
                                        href="{{ url_for(
                                            'download_previous_report',
                                            report_key=report['key']
                                        ) }}"
                                        onclick="showToast('Report download started')"
                                    >
                                        Download
                                    </a>


                                </div>


                            </div>


                        {% endfor %}


                        </div>


                    {% else %}


                        <div class="empty">

                            <div class="empty-icon">
                                ◫
                            </div>

                            No previous reports found.

                        </div>


                    {% endif %}

                </section>


                <div class="footer">

                    CloudMart Operations Dashboard
                    ·
                    Environment: {{ environment or "Unknown" }}
                    ·
                    Reports stored in Amazon S3

                </div>


            {% endif %}

        </div>

    </main>

</div>


<!-- =========================
     REPORT MODAL
     ========================= -->

<div
    id="reportModal"
    class="modal"
    onclick="closeModalFromBackground(event)"
>

    <div class="modal-content">

        <div class="modal-header">

            <div>

                <div
                    id="reportModalTitle"
                    class="modal-title"
                >
                    Latest Daily Report
                </div>

                <div class="modal-subtitle">
                    CSV report preview
                </div>

            </div>


            <button
                class="close"
                onclick="closeReportModal()"
                aria-label="Close"
            >
                ×
            </button>

        </div>


        <div class="modal-body">

            <div
                id="reportLoading"
                class="empty"
            >
                Loading report...
            </div>


            <pre
                id="reportContent"
                class="csv-preview"
                style="display:none;"
            ></pre>

        </div>

    </div>

</div>


<!-- =========================
     ORDERS MODAL
     ========================= -->

{% if not error and orders %}

<div
    id="ordersModal"
    class="modal"
    onclick="closeOrdersFromBackground(event)"
>

    <div class="modal-content">

        <div class="modal-header">

            <div>

                <div class="modal-title">
                    Detailed Order Information
                </div>

                <div class="modal-subtitle">
                    Complete order-item records from the latest report
                </div>

            </div>


            <button
                class="close"
                onclick="closeOrdersModal()"
                aria-label="Close"
            >
                ×
            </button>

        </div>


        <div class="modal-body">

            <div class="table-wrapper">

                <table>

                    <thead>

                        <tr>

                            {% for column in order_columns %}

                                <th>
                                    {{ column }}
                                </th>

                            {% endfor %}

                        </tr>

                    </thead>


                    <tbody>


                    {% for order in orders %}


                        <tr>


                            {% for column in order_columns %}

                                <td>
                                    {{ order[column] }}
                                </td>

                            {% endfor %}


                        </tr>


                    {% endfor %}


                    </tbody>

                </table>

            </div>

        </div>

    </div>

</div>

{% endif %}


<div id="toast" class="toast"></div>


<script>

    /* =========================
       TOAST
       ========================= */

    let toastTimer = null;


    function showToast(message) {

        const toast = document.getElementById("toast");

        toast.textContent = message;

        toast.classList.add("show");


        clearTimeout(toastTimer);


        toastTimer = setTimeout(
            function() {
                toast.classList.remove("show");
            },
            2600
        );

    }


    /* =========================
       REPORT MODAL
       ========================= */

    async function openReport(url, title) {

        const modal = document.getElementById("reportModal");
        const content = document.getElementById("reportContent");
        const loading = document.getElementById("reportLoading");
        const titleElement =
            document.getElementById("reportModalTitle");


        titleElement.textContent =
            title || "Daily Report";


        content.style.display = "none";
        loading.style.display = "block";

        loading.textContent = "Loading report...";


        modal.classList.add("open");

        document.body.style.overflow = "hidden";


        try {

            const response = await fetch(url);


            if (!response.ok) {
                throw new Error(
                    "Unable to retrieve report."
                );
            }


            const text = await response.text();


            content.textContent = text;

            loading.style.display = "none";

            content.style.display = "block";


        } catch (error) {

            loading.textContent =
                "Unable to load this report: " + error.message;

        }

    }


    function openLatestReport() {

        openReport(
            "{{ url_for('view_report') }}",
            "Latest Daily Report"
        );

    }


    function openPreviousReport(url, name) {

        openReport(
            url,
            name
        );

    }


    function closeReportModal() {

        document
            .getElementById("reportModal")
            .classList.remove("open");

        document.body.style.overflow = "";

    }


    function closeModalFromBackground(event) {

        if (
            event.target ===
            document.getElementById("reportModal")
        ) {

            closeReportModal();

        }

    }


    /* =========================
       ORDERS MODAL
       ========================= */

    function openOrdersModal() {

        const modal =
            document.getElementById("ordersModal");

        if (!modal) {
            return;
        }

        modal.classList.add("open");

        document.body.style.overflow = "hidden";

    }


    function closeOrdersModal() {

        const modal =
            document.getElementById("ordersModal");

        if (!modal) {
            return;
        }

        modal.classList.remove("open");

        document.body.style.overflow = "";

    }


    function closeOrdersFromBackground(event) {

        if (
            event.target ===
            document.getElementById("ordersModal")
        ) {

            closeOrdersModal();

        }

    }


    /* =========================
       PRODUCT SEARCH / FILTER
       ========================= */

    function filterProducts() {

        const searchInput =
            document.getElementById("productSearch");

        const filterInput =
            document.getElementById("stockFilter");


        if (!searchInput || !filterInput) {
            return;
        }


        const search =
            searchInput.value
                .toLowerCase()
                .trim();


        const filter =
            filterInput.value;


        const rows =
            document.querySelectorAll(".product-row");


        let visibleCount = 0;


        rows.forEach(
            function(row) {

                const name =
                    row.dataset.name || "";


                const stock =
                    row.dataset.stock || "";


                const matchesSearch =
                    name.includes(search);


                const matchesFilter =
                    filter === "all" ||
                    stock === filter;


                if (
                    matchesSearch &&
                    matchesFilter
                ) {

                    row.style.display = "";

                    visibleCount++;

                } else {

                    row.style.display = "none";

                }

            }
        );


        const empty =
            document.getElementById(
                "noProductsFound"
            );


        if (empty) {

            empty.style.display =
                visibleCount === 0
                    ? "block"
                    : "none";

        }

    }


    /* =========================
       KEYBOARD CONTROLS
       ========================= */

    document.addEventListener(
        "keydown",
        function(event) {

            if (event.key === "Escape") {

                closeReportModal();

                closeOrdersModal();

            }

        }
    );


    /* =========================
       NAVIGATION
       ========================= */

    document.querySelectorAll(".nav-link").forEach(
        function(link) {

            link.addEventListener(
                "click",
                function() {

                    document
                        .querySelectorAll(".nav-link")
                        .forEach(
                            function(item) {
                                item.classList.remove(
                                    "active"
                                );
                            }
                        );


                    link.classList.add("active");

                }
            );

        }
    );

</script>


</body>
</html>
"""


def get_latest_report_key():

    response = s3.list_objects_v2(
        Bucket=REPORT_BUCKET,
        Prefix=REPORT_PREFIX
    )

    objects = response.get("Contents", [])

    if not objects:
        raise RuntimeError("No reports found in S3.")

    csv_objects = [
        item
        for item in objects
        if item["Key"].lower().endswith(".csv")
    ]

    if not csv_objects:
        raise RuntimeError("No CSV reports found in S3.")

    latest = max(
        csv_objects,
        key=lambda item: item["LastModified"]
    )

    return latest["Key"]


def get_previous_reports():

    response = s3.list_objects_v2(
        Bucket=REPORT_BUCKET,
        Prefix=REPORT_PREFIX
    )

    objects = response.get("Contents", [])

    reports = []

    for item in objects:

        key = item["Key"]

        if not key.lower().endswith(".csv"):
            continue

        reports.append(
            {
                "key": key,
                "name": os.path.basename(key),
                "last_modified": item["LastModified"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            }
        )

    reports.sort(
        key=lambda item: item["last_modified"],
        reverse=True
    )

    return reports


def get_report_content(report_key):

    response = s3.get_object(
        Bucket=REPORT_BUCKET,
        Key=report_key
    )

    return response["Body"].read().decode("utf-8")


def load_report():

    key = get_latest_report_key()

    content = get_report_content(key)

    lines = list(
        csv.reader(
            io.StringIO(content)
        )
    )

    report_date = ""
    report_window = ""
    environment = ""

    for row in lines:

        if len(row) >= 2 and row[0] == "Report Date":
            report_date = row[1]

        elif len(row) >= 2 and row[0] == "Report Window":
            report_window = row[1]

        elif len(row) >= 2 and row[0] == "Environment":
            environment = row[1]


    order_columns = [
        "Order ID",
        "Customer ID",
        "Created Time",
        "Updated Time",
        "Order Status",
        "Total Amount",
        "Order Item ID",
        "Product ID",
        "Quantity",
        "Unit Price",
        "Subtotal",
        "Product Name",
        "Current Stock",
        "Product Status"
    ]


    product_columns = [
        "Product ID",
        "Product Name",
        "Price",
        "Current Stock",
        "Product Status",
        "Low Stock"
    ]


    orders = []
    products = []

    order_header_index = None
    product_header_index = None


    for index, row in enumerate(lines):

        if row == order_columns:
            order_header_index = index

        if row == product_columns:
            product_header_index = index


    if order_header_index is not None:

        start = order_header_index + 1

        end = product_header_index

        if end is None:
            end = len(lines)

        for row in lines[start:end]:

            if row and len(row) == len(order_columns):

                orders.append(
                    dict(
                        zip(
                            order_columns,
                            row
                        )
                    )
                )


    if product_header_index is not None:

        start = product_header_index + 1

        for row in lines[start:]:

            if row and len(row) == len(product_columns):

                products.append(
                    dict(
                        zip(
                            product_columns,
                            row
                        )
                    )
                )


    low_stock_count = sum(
        1
        for product in products
        if product["Low Stock"].upper() == "YES"
    )


    order_status_counts = Counter(
        order["Order Status"].upper()
        for order in orders
    )


    previous_reports = get_previous_reports()


    return {
        "report_key": key,
        "report_date": report_date,
        "report_window": report_window,
        "environment": environment,
        "orders": orders,
        "products": products,
        "order_columns": order_columns,
        "low_stock_count": low_stock_count,
        "order_status_counts": order_status_counts,
        "previous_reports": previous_reports
    }

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template_string(LOGIN_HTML, error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if username != "admin":
        return render_template_string(
            LOGIN_HTML,
            error="Invalid username or password."
        ), 401

    try:
        admin_token = get_admin_token()
    except Exception:
        app.logger.exception("Unable to retrieve dashboard admin token")
        return render_template_string(
            LOGIN_HTML,
            error="Login service is unavailable."
        ), 500

    if password != admin_token:
        return render_template_string(
            LOGIN_HTML,
            error="Invalid username or password."
        ), 401

    session["authenticated"] = True
    session["username"] = username

    return redirect(url_for("dashboard"))

@app.before_request
def require_login():
    if request.path == "/login":
        return None

    if not session.get("authenticated"):
        return redirect(url_for("login"))

    return None

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def dashboard():

    try:

        data = load_report()

        return render_template_string(
            HTML,
            error=None,
            **data
        )

    except Exception as exc:

        return render_template_string(
            HTML,
            error=str(exc)
        ), 500


@app.route("/report/view")
def view_report():

    key = get_latest_report_key()

    content = get_report_content(key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "inline"
        }
    )


@app.route("/report/download")
def download_report():

    key = get_latest_report_key()

    content = get_report_content(key)

    filename = os.path.basename(key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        }
    )


@app.route("/report/view/<path:report_key>")
def view_previous_report(report_key):

    content = get_report_content(report_key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "inline"
        }
    )


@app.route("/report/download/<path:report_key>")
def download_previous_report(report_key):

    content = get_report_content(report_key)

    filename = os.path.basename(report_key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        }
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )