import React, { useState, useEffect, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts';
import {
  Mail, ShieldAlert, Send, BarChart2, LogOut, Plus, RefreshCw, FileText, User, Lock, Mail as MailIcon, ArrowLeft
} from 'lucide-react';
import './App.css';

const API_BASE = "http://localhost:8000";

function App() {
  // Navigation & Auth State
  const [view, setView] = useState('auth-login');
  const [user, setUser] = useState(null);
  const [folder, setFolder] = useState('inbox');
  const [showCompose, setShowCompose] = useState(false);

  // Data State
  const [emails, setEmails] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [stats, setStats] = useState({ ham: 0, spam: 0, ads: 0, social: 0, total: 0 });
  const [loading, setLoading] = useState(false);
  const getToken = () => localStorage.getItem('token');

  // Form State
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '' });
  const [emailForm, setEmailForm] = useState({ recipient: '', subject: '', body: '' });

  // UI State
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);

  // --- Auth Logic ---
  const handleAuth = async (e) => {
    e.preventDefault();

    // Validate empty fields
    if (view === 'auth-register' && !authForm.username) {
      alert("Vui lòng nhập tên hiển thị!");
      return;
    }
    if (!authForm.email || !authForm.password) {
      alert("Vui lòng nhập email và mật khẩu!");
      return;
    }
    if (view === 'auth-register' && authForm.password.length < 6) {
      alert("Mật khẩu phải có ít nhất 6 ký tự!");
      return;
    }

    const endpoint = view === 'auth-login' ? '/login' : '/register';
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authForm)
      });
      const data = await res.json();
      if (res.ok) {
        if (view === 'auth-login') {
          setUser(data.user);
          localStorage.setItem('token', data.access_token);
          setView('mailbox');
        } else {
          alert("Đăng ký thành công! Hãy đăng nhập.");
          setView('auth-login');
        }
      } else {
        alert(data.detail || "Lỗi xác thực");
      }
    } catch (err) {
      alert("Lỗi kết nối");
    }
  };

  const logout = () => {
    setUser(null);
    localStorage.removeItem('token');
    setView('auth-login');
  };

  // --- Helpers ---
  const parseDate = (dateStr) => {
    if (!dateStr) return new Date();
    // Ensure the date is treated as UTC if it doesn't have a timezone suffix
    const normalized = (dateStr.endsWith('Z') || dateStr.includes('+'))
      ? dateStr
      : `${dateStr.replace(' ', 'T')}Z`;
    return new Date(normalized);
  };

  const formatEmailTime = (dateStr) => {
    const date = parseDate(dateStr);
    const now = new Date();
    const diffInMs = now - date;
    const oneDayInMs = 24 * 60 * 60 * 1000;

    if (diffInMs > oneDayInMs) {
      // More than 1 day: show date (dd/mm)
      return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
    } else {
      // Less than 1 day: show time (hh:mm)
      return date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
    }
  };

  // --- Email Logic ---
  const fetchEmails = async () => {
    if (!user) return;
    try {
      const endpoint = folder === 'sent'
        ? `${API_BASE}/emails?sender=${user.email}`
        : `${API_BASE}/emails?recipient=${user.email}`;
      const res = await fetch(endpoint, {
        headers: { 'Authorization': `Bearer ${getToken()}` }
      });
      const data = await res.json();
      setEmails(data);
    } catch (err) {
      console.error("Fetch error", err);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/stats`, {
        headers: { 'Authorization': `Bearer ${getToken()}` }
      });
      const data = await res.json();
      setStats(data);
    } catch (err) {
      console.error("Stats error", err);
    }
  };

  useEffect(() => {
    if (user) {
      fetchEmails();
      fetchStats();
      const interval = setInterval(() => {
        fetchEmails();
        fetchStats();
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [user, folder]);

  const handleSend = async () => {
    // Validate empty fields
    if (!emailForm.recipient || !emailForm.subject || !emailForm.body) {
      alert("Vui lòng điền đầy đủ thông tin (Người nhận, Tiêu đề, Nội dung)!");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/send`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getToken()}` 
        },
        body: JSON.stringify({ ...emailForm, sender: user.email })
      });
      const data = await res.json();
      if (res.ok) {
        setShowCompose(false);
        setEmailForm({ recipient: '', subject: '', body: '' });
        alert("Thư đã được gửi!");
        fetchEmails();
      } else {
        // Handle FastAPI/Pydantic validation errors (often an array)
        let errorMsg = "Lỗi khi gửi thư";
        if (typeof data.detail === 'string') {
          errorMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          // Extract the last error message or the first one
          errorMsg = data.detail[0]?.msg || errorMsg;
          // Localize common Pydantic errors
          if (errorMsg.includes("value is not a valid email address")) {
            errorMsg = "Địa chỉ email không hợp lệ!";
          }
        }
        alert(errorMsg);
      }
    } catch (err) {
      alert("Lỗi kết nối máy chủ");
    }
  };

  const handleOpenEmail = async (email) => {
    setSelectedEmail(email);
    if (!email.is_read && folder !== 'sent') {
      try {
        await fetch(`${API_BASE}/emails/${email.id}/read`, { 
          method: 'PATCH',
          headers: { 'Authorization': `Bearer ${getToken()}` }
        });
        // Update local state to remove bold immediatey
        setEmails(prev => prev.map(e => e.id === email.id ? { ...e, is_read: true } : e));
      } catch (err) {
        console.error("Mark as read error", err);
      }
    }
  };

  // --- Big Data Logic ---
  const handleFileUpload = async (file) => {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/upload-csv`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${getToken()}` },
        body: formData
      });
      const data = await res.json();
      if (res.ok) {
        alert("Đã nhận tệp! Spark đang tiến hành phân loại hàng triệu bản ghi...");
        fetchStats();
      }
    } catch (err) {
      alert("Lỗi tải lên");
    }
  };

  // --- Renderers ---

  if (view.startsWith('auth')) {
    return (
      <div className="auth-container">
        <div className="auth-card">
          <div className="auth-logo">
            <MailIcon size={32} color="#1a73e8" />
            <span>My Mail</span>
          </div>
          <h1 className="auth-title">{view === 'auth-login' ? 'Đăng nhập' : 'Tạo tài khoản'}</h1>
          <p className="auth-subtitle">Sử dụng tài khoản của bạn</p>

          <form onSubmit={handleAuth}>
            {view === 'auth-register' && (
              <div className="auth-input-group">
                <input
                  className="auth-input"
                  placeholder="Tên hiển thị"
                  required
                  value={authForm.username}
                  onChange={e => setAuthForm({ ...authForm, username: e.target.value })}
                />
              </div>
            )}
            <div className="auth-input-group">
              <input
                className="auth-input"
                type="email"
                placeholder="Email"
                required
                value={authForm.email}
                onChange={e => setAuthForm({ ...authForm, email: e.target.value })}
              />
            </div>
            <div className="auth-input-group">
              <input
                className="auth-input"
                type="password"
                placeholder="Mật khẩu"
                required
                value={authForm.password}
                onChange={e => setAuthForm({ ...authForm, password: e.target.value })}
              />
            </div>
            <button className="auth-btn" type="submit">
              {view === 'auth-login' ? 'Tiếp theo' : 'Đăng ký'}
            </button>
          </form>

          <div className="auth-toggle">
            {view === 'auth-login' ? (
              <>Chưa có tài khoản? <button className="auth-link" onClick={() => setView('auth-register')}>Tạo tài khoản</button></>
            ) : (
              <>Đã có tài khoản? <button className="auth-link" onClick={() => setView('auth-login')}>Đăng nhập</button></>
            )}
          </div>
        </div>
      </div>
    );
  }

  const chartData = [
    { name: 'Hộp thư (Inbox)', value: stats.ham || 0, color: '#1e8e3e' },
    { name: 'Thư rác (Spam)', value: stats.spam || 0, color: '#d93025' },
    { name: 'Quảng cáo (Ads)', value: stats.ads || 0, color: '#fbbc04' },
    { name: 'Mạng xã hội (Social)', value: stats.social || 0, color: '#1a73e8' }
  ];

  if (user && user.role === 'admin') {
    return (
      <div className="app-container">
        <div className="sidebar">
          <div style={{ padding: '16px', fontWeight: 500, fontSize: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert color="#d93025" /> Admin Panel
          </div>
          <div className="nav-item active"><BarChart2 size={20} /> Quản lý hệ thống</div>
          <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border-color)', padding: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: '#d93025', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px' }}>
                A
              </div>
              <div style={{ fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                <strong>{user.username}</strong><br />
                <span style={{ color: 'var(--text-secondary)' }}>{user.email}</span>
              </div>
            </div>
            <button className="nav-item" style={{ width: '100%', padding: '8px', border: '1px solid var(--border-color)', borderRadius: '4px' }} onClick={logout}>
              <LogOut size={16} /> Đăng xuất
            </button>
          </div>
        </div>
        <div className="main-content" style={{ padding: '40px' }}>
          <h1>Trang quản lý dành cho Admin</h1>
          <p>Chào mừng {user.username}. Tính năng này sẽ được thiết kế và phát triển sau.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div className="sidebar">
        <div style={{ padding: '16px', fontWeight: 500, fontSize: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <MailIcon color="#1a73e8" />
          Mail
        </div>

        <button className="compose-btn" onClick={() => setShowCompose(true)}>
          <Plus size={24} /> Soạn thư
        </button>

        <div className={`nav-item ${view === 'mailbox' && folder === 'inbox' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('inbox'); }}>
          <Mail size={20} /> Hộp thư đến
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'ads' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('ads'); setSelectedEmail(null); }}>
          <MailIcon size={20} /> Quảng cáo
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'social' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('social'); setSelectedEmail(null); }}>
          <MailIcon size={20} /> Mạng xã hội
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'spam' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('spam'); setSelectedEmail(null); }}>
          <ShieldAlert size={20} /> Thư rác
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'sent' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('sent'); setSelectedEmail(null); }}>
          <Send size={20} /> Thư đã gửi
        </div>

        <div className={`nav-item ${view === 'analysis' ? 'active' : ''}`}
          onClick={() => setView('analysis')}>
          <BarChart2 size={20} /> Phân tích Mail
        </div>

        <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border-color)', padding: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
            <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: '#1a73e8', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px' }}>
              {user.username[0].toUpperCase()}
            </div>
            <div style={{ fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <strong>{user.username}</strong><br />
              <span style={{ color: 'var(--text-secondary)' }}>{user.email}</span>
            </div>
          </div>
          <button className="nav-item" style={{ width: '100%', padding: '8px', border: '1px solid var(--border-color)', borderRadius: '4px' }} onClick={logout}>
            <LogOut size={16} /> Đăng xuất
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="main-content">
        {view === 'mailbox' ? (
          <>
            <div className="toolbar">
              {selectedEmail ? (
                <button className="icon-btn back-btn" onClick={() => setSelectedEmail(null)} title="Quay lại">
                  <ArrowLeft size={18} />
                </button>
              ) : (
                <button className="icon-btn" onClick={fetchEmails} title="Tải lại">
                  <RefreshCw size={18} />
                </button>
              )}
              <span style={{ fontWeight: 500 }}>
                {selectedEmail ? 'Chi tiết thư' : (
                  folder === 'inbox' ? 'Hộp thư đến' : 
                  folder === 'ads' ? 'Quảng cáo' :
                  folder === 'social' ? 'Mạng xã hội' :
                  folder === 'sent' ? 'Thư đã gửi' : 'Thư rác')}
              </span>
            </div>

            <div className="email-list">
              {selectedEmail ? (
                <div className="email-detail">
                  <div className="detail-header">
                    <h2>{selectedEmail.subject}</h2>
                    <div className="detail-meta">
                      <div className="meta-info">
                        <strong>{selectedEmail.sender_name || selectedEmail.sender}</strong>
                        <span> &lt;{selectedEmail.sender}&gt;</span>
                        <div className="to-info">Tới: {selectedEmail.recipient_name || selectedEmail.recipient}</div>
                      </div>
                      <div className="detail-time">
                        {parseDate(selectedEmail.created_at).toLocaleString('vi-VN')}
                      </div>
                    </div>
                  </div>
                  <div className="detail-body">
                    {selectedEmail.body}
                  </div>
                </div>
              ) : (
                <>
                  {emails.filter(e => folder === 'sent' ? true : e.category === folder).map(email => (
                    <div key={email.id} className={`email-item ${(!email.is_read && folder !== 'sent') ? 'unread' : ''}`} onClick={() => handleOpenEmail(email)}>
                      <div className="email-sender">
                        {folder === 'sent' ? (email.recipient_name || email.recipient) : (email.sender_name || email.sender)}
                      </div>
                      <div className="email-content">
                        <span className="email-subject">{email.subject}</span>
                        <span className="email-body"> — {email.body}</span>
                      </div>
                      <div className="email-time">
                        {formatEmailTime(email.created_at)}
                      </div>
                      {email.category === 'spam' && folder !== 'spam' && <span className="badge spam-badge">SPAM</span>}
                      {email.category === 'ads' && folder !== 'ads' && <span className="badge" style={{backgroundColor: '#fbbc04', color: 'white'}}>ADS</span>}
                    </div>
                  ))}
                  {emails.filter(e => folder === 'sent' ? true : e.category === folder).length === 0 && (
                    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                      Không có thư!
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <div className="analysis-container">
            <div className="analysis-header">
              <h1>Phân tích email</h1>
              <p style={{ color: 'var(--text-secondary)' }}>Sử dụng Apache Spark để phân loại email từ CSV</p>
            </div>

            <div
              className={`drop-zone ${isDragging ? 'dragging' : ''}`}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => { e.preventDefault(); setIsDragging(false); if (e.dataTransfer.files[0]) handleFileUpload(e.dataTransfer.files[0]); }}
              onClick={() => fileInputRef.current?.click()}
            >
              <FileText className="drop-zone-icon" color="#1a73e8" />
              <p>Kéo và thả file CSV vào đây để Spark phân loại</p>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Hỗ trợ file kích thước lớn</span>
              <input type="file" ref={fileInputRef} style={{ display: 'none' }} accept=".csv" onChange={e => handleFileUpload(e.target.files[0])} />
            </div>

            <div className="analysis-grid">
              <div className="card">
                <h3>Thống kê tổng quan</h3>
                <div className="stat-item" style={{ marginTop: '20px' }}>
                  <div className="stat-label">Tổng số email đã xử lý</div>
                  <div className="stat-value">{stats.total.toLocaleString()}</div>
                </div>
                <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                  <div className="stat-item">
                    <div className="stat-label">Hộp thư</div>
                    <div className="stat-value" style={{ color: '#1e8e3e', fontSize: '24px' }}>{(stats.ham || 0).toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Thư rác</div>
                    <div className="stat-value" style={{ color: '#d93025', fontSize: '24px' }}>{(stats.spam || 0).toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Quảng cáo</div>
                    <div className="stat-value" style={{ color: '#fbbc04', fontSize: '24px' }}>{(stats.ads || 0).toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Mạng xã hội</div>
                    <div className="stat-value" style={{ color: '#1a73e8', fontSize: '24px' }}>{(stats.social || 0).toLocaleString()}</div>
                  </div>
                </div>
              </div>

              <div className="card">
                <h3>Tỉ lệ phân loại</h3>
                <div className="chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={chartData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value"
                      >
                        {chartData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            <div className="card" style={{ marginTop: '24px' }}>
              <h3>Hiệu suất Phân loại</h3>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip />
                    <Bar dataKey="value" fill="#1a73e8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Compose Modal */}
      {showCompose && (
        <div className="modal-overlay">
          <div className="modal-header">
            <span>Thư mới</span>
            <button onClick={() => setShowCompose(false)} style={{ border: 'none', background: 'none', color: 'white', cursor: 'pointer', fontSize: '18px' }}>×</button>
          </div>
          <div className="modal-body">
            <input
              placeholder="Người nhận (email)"
              value={emailForm.recipient}
              onChange={e => setEmailForm({ ...emailForm, recipient: e.target.value })}
            />
            <input
              placeholder="Tiêu đề"
              value={emailForm.subject}
              onChange={e => setEmailForm({ ...emailForm, subject: e.target.value })}
            />
            <textarea
              placeholder="Nội dung thư..."
              value={emailForm.body}
              onChange={e => setEmailForm({ ...emailForm, body: e.target.value })}
            />
          </div>
          <div className="modal-footer">
            <button className="send-btn" onClick={handleSend}>Gửi</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
