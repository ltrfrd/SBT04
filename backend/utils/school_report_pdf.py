from io import BytesIO                                                         # In-memory PDF buffer

from reportlab.lib import colors                                               # Table and border colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet           # PDF text styles
from reportlab.lib.units import inch                                           # Page measurements
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # PDF building blocks


# -----------------------------------------------------------
# School Attendance PDF Builder
# Create printable school attendance PDF from school report payload
# -----------------------------------------------------------
def build_school_attendance_pdf(report_data: dict) -> bytes:
    """Build printable school attendance PDF and return raw bytes."""          # PDF export for school report

    buffer = BytesIO()                                                         # In-memory output stream

    doc = SimpleDocTemplate(                                                   # Standard letter-size printable PDF
        buffer,
        pagesize=(8.5 * inch, 11 * inch),
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )

    styles = getSampleStyleSheet()                                             # Base reportlab styles

    title_style = ParagraphStyle(                                              # Centered report title
        "SchoolReportTitle",
        parent=styles["Title"],
        alignment=1,
    )

    meta_style = ParagraphStyle(
        "SchoolReportMeta",
        parent=styles["Normal"],
        alignment=0,
        spaceAfter=0,                                                     # Remove vertical gap
        leading=12,                                                       # Tight line spacing
    )

    section_style = ParagraphStyle(                                            # Route/run section heading
        "SchoolReportSection",
        parent=styles["Heading3"],
        spaceAfter=8,
    )

    elements = []                                                              # PDF flow elements

    school_name = report_data.get("school_name", "Unknown School")             # School display name
    report_date = report_data.get("date", "")                                  # Optional report date
    driver_name = report_data.get("driver_name", "Not Assigned")               # Optional driver name
    routes = report_data.get("routes", [])                                     # Route groups

    elements.append(Paragraph("School Bus Attendance Report", title_style))    # Main title
    elements.append(Spacer(1, 10))

    for route in routes:                                                       # Each route group
        route_number = route.get("route_number", "N/A")                        # Route label
        runs = route.get("runs", [])                                           # Run entries under route

        for run in runs:                                                       # Each AM/PM run
            raw_run_type = str(run.get("run_type", "")).strip()                # Original run type value
            run_type = raw_run_type.split()[-1].upper() if raw_run_type else "N/A"  # Keep only AM / PM
            run_date = run.get("date", "")                                     # Run date

            students = run.get("students", [])                                 # Student rows
            students = sorted(                                                 # Present first, absent last
                students,
                key=lambda s: (s.get("status") == "absent", s.get("student_name") or "")
            )
            present_total = sum(                                               # Present count
                1 for student in students if student.get("status") == "present"
            )
            absent_total = sum(                                                # Absent count
                1 for student in students if student.get("status") == "absent"
            )

            header_table = Table(
               [
                    ["School:", school_name],
                    ["Driver:", driver_name],
                    ["Route:", route_number],
                    ["Run:", run_type],        # label changed here
                    ["Date:", run_date],
                ],
                colWidths=[1.4 * inch, 5.0 * inch],
            )

            header_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 1),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ]
                )
            )

            elements.append(header_table)                                              # Header block
            elements.append(Spacer(1, 6))
            
            table_data = [["Student Name", "Status"]]                          # Table header

            for student in students:                                                       # Student rows
                status = student.get("status", "")

                if status == "present":                                                    # Green present
                    status_text = '<font color="green">Present</font>'
                else:                                                                      # Red absent
                    status_text = '<font color="red">Absent</font>'

                table_data.append(
                    [   
                        student.get("student_name", ""),
                        Paragraph(status_text, styles["Normal"]),                          # Colored status
                    ]
                )
            student_table = Table(                                             # Attendance table
                table_data,
                colWidths=[4.8 * inch, 1.6 * inch],
                repeatRows=1,
            )
            student_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("ALIGN", (1, 1), (1, -1), "CENTER"),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ]
                )
            )

            totals_table = Table(                                              # Present / absent totals
                [
                    ["Total Present", present_total],
                    ["Total Absent", absent_total],
                ],
                colWidths=[4.8 * inch, 1.6 * inch],
            )
            totals_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("ALIGN", (1, 0), (1, -1), "CENTER"),
                    ]
                )
            )

            elements.append(student_table)                                     # Student attendance
            elements.append(Spacer(1, 12))
            elements.append(totals_table)                                      # Totals
            elements.append(Spacer(1, 18))

    doc.build(elements)                                                        # Render PDF
    pdf_bytes = buffer.getvalue()                                              # Extract final bytes
    buffer.close()                                                             # Close in-memory stream

    return pdf_bytes                                                           # Return raw PDF content