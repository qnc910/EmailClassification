import React, { useState, useEffect, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts';
import {
  Mail, ShieldAlert, Send, BarChart2, LogOut, Plus, RefreshCw, FileText, User, Lock, Mail as MailIcon, ArrowLeft, Settings, Trash2, Users, Edit, Search
} from 'lucide-react';
import './App.css';

const API_BASE = "http://localhost:8000";

const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    const subcategories = data.subcategories || {};
    const subcategoryList = Object.entries(subcategories);

    return (
      <div className="custom-tooltip" style={{
        backgroundColor: 'rgba(255, 255, 255, 0.95)',
        padding: '12px 16px',
        border: '1px solid #e0e0e0',
        borderRadius: '8px',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
        backdropFilter: 'blur(4px)'
      }}>
        <p className="label" style={{ margin: 0, fontWeight: 'bold', fontSize: '14px', color: data.color || '#333', borderBottom: '1px solid #eee', paddingBottom: '6px', marginBottom: '6px' }}>
          {`${data.name}: ${data.value.toLocaleString()}`}
        </p>
        {subcategoryList.length > 0 ? (
          <div style={{ fontSize: '12px', color: '#555' }}>
            <div style={{ fontWeight: '600', marginBottom: '4px', color: '#666' }}>Nhóm con (Subcategories):</div>
            <ul style={{ margin: 0, paddingLeft: '16px', listStyleType: 'disc' }}>
              {subcategoryList.map(([subName, subValue]) => (
                <li key={subName} style={{ marginBottom: '2px' }}>
                  <span style={{ fontWeight: '500' }}>{subName.charAt(0).toUpperCase() + subName.slice(1)}</span>: {subValue.toLocaleString()}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div style={{ fontSize: '12px', color: '#888', fontStyle: 'italic' }}>Không có nhóm con</div>
        )}
      </div>
    );
  }
  return null;
};

function App() {
  // Navigation & Auth State
  const [view, setView] = useState('auth-login');
  const [user, setUser] = useState(null);
  const [folder, setFolder] = useState('inbox');
  const [showCompose, setShowCompose] = useState(false);

  // Data State
  const [emails, setEmails] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [stats, setStats] = useState({ ham: 0, spam: 0, ads: 0, social: 0, total: 0, subcategories: {}, subcategory_details: { inbox: {}, spam: {}, ads: {}, social: {} } });
  const [subcategory, setSubcategory] = useState('all');
  const [availableSubcategories, setAvailableSubcategories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const getToken = () => localStorage.getItem('token');

  // Form State
  const [authForm, setAuthForm] = useState({ username: '', email: '', password: '' });
  const [emailForm, setEmailForm] = useState({ recipient: '', subject: '', body: '' });
  const [profileForm, setProfileForm] = useState({ username: '' });
  const [passwordForm, setPasswordForm] = useState({ old_password: '', new_password: '', confirm_password: '' });
  const [showSettingsMenu, setShowSettingsMenu] = useState(false);
  const [settingsModal, setSettingsModal] = useState(null); // 'profile' or 'password'

  // UI State
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);
  const [undoToast, setUndoToast] = useState(null);

  // Admin State
  const [adminView, setAdminView] = useState('users'); // 'users' or 'stats'
  const [allUsers, setAllUsers] = useState([]);
  const [adminStats, setAdminStats] = useState({ ham: 0, spam: 0, ads: 0, social: 0, total: 0, subcategories: {}, subcategory_details: { inbox: {}, spam: {}, ads: {}, social: {} } });
  const [searchQuery, setSearchQuery] = useState('');
  const [editUserModal, setEditUserModal] = useState(null);
  const [editUserForm, setEditUserForm] = useState({ password: '', role: 'user' });

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
  const fetchSubcategories = async (cat) => {
    try {
      const res = await fetch(`${API_BASE}/emails/subcategories?category=${cat}`, {
        headers: { 'Authorization': `Bearer ${getToken()}` }
      });
      if (res.ok) {
        const data = await res.json();
        setAvailableSubcategories(data);
      }
    } catch (err) {
      console.error("Subcategories fetch error", err);
    }
  };

  const fetchEmails = async () => {
    if (!user) return;
    try {
      const limit = 50;
      const offset = (page - 1) * limit;
      let endpoint;
      if (folder === 'sent') {
        endpoint = `${API_BASE}/emails?sender=${user.email}&limit=${limit}&offset=${offset}`;
      } else {
        endpoint = `${API_BASE}/emails?recipient=${user.email}&category=${folder}&limit=${limit}&offset=${offset}`;
        if (subcategory && subcategory !== 'all') {
          endpoint += `&subcategory=${subcategory}`;
        }
      }
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

  const fetchAdminData = async () => {
    if (!user || user.role !== 'admin') return;
    try {
      const headers = { 'Authorization': `Bearer ${getToken()}` };
      const [usersRes, statsRes] = await Promise.all([
        fetch(`${API_BASE}/admin/users`, { headers }),
        fetch(`${API_BASE}/admin/stats`, { headers })
      ]);
      if (usersRes.ok) setAllUsers(await usersRes.json());
      if (statsRes.ok) setAdminStats(await statsRes.json());
    } catch (err) {
      console.error("Admin fetch error", err);
    }
  };

  const handleAdminUpdateUser = async () => {
    if (!editUserModal) return;
    try {
      const res = await fetch(`${API_BASE}/admin/users/${editUserModal.id}`, {
        method: 'PATCH',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getToken()}` 
        },
        body: JSON.stringify(editUserForm)
      });
      if (res.ok) {
        setEditUserModal(null);
        fetchAdminData();
        alert("Cập nhật thành công!");
      } else {
        alert("Lỗi cập nhật");
      }
    } catch (err) {
      alert("Lỗi kết nối");
    }
  };

  const handleAdminDeleteUser = async (userId) => {
    if (!window.confirm("Bạn có chắc chắn muốn xóa người dùng này?")) return;
    try {
      const res = await fetch(`${API_BASE}/admin/users/${userId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${getToken()}` }
      });
      const data = await res.json();
      if (res.ok) {
        fetchAdminData();
        alert("Đã xóa người dùng");
      } else {
        alert(data.detail || "Lỗi khi xóa");
      }
    } catch (err) {
      alert("Lỗi kết nối");
    }
  };

  // Check auth on mount
  useEffect(() => {
    const checkAuth = async () => {
      const token = getToken();
      if (token) {
        try {
          const res = await fetch(`${API_BASE}/user/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
          });
          if (res.ok) {
            const userData = await res.json();
            setUser(userData);
            setView('mailbox');
          } else {
            localStorage.removeItem('token');
          }
        } catch (err) {
          console.error("Auth check error", err);
        }
      }
    };
    checkAuth();
  }, []);

  useEffect(() => {
    if (user) {
      setProfileForm({ username: user.username });
      if (user.role === 'admin') {
        fetchAdminData();
      } else {
        fetchEmails();
        fetchStats();
        if (folder === 'social' || folder === 'ads') {
          fetchSubcategories(folder);
        }
      }
      const interval = setInterval(() => {
        if (user.role === 'admin') {
           fetchAdminData();
        } else {
           fetchEmails();
           fetchStats();
           if (folder === 'social' || folder === 'ads') {
             fetchSubcategories(folder);
           }
        }
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [user, folder, subcategory, page]);

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

  const handleDeleteEmail = async (e, emailId) => {
    e.stopPropagation();
    try {
      const emailToDelete = emails.find(em => em.id === emailId);
      
      const res = await fetch(`${API_BASE}/emails/${emailId}/delete`, {
        method: 'PATCH',
        headers: { 'Authorization': `Bearer ${getToken()}` }
      });
      if (res.ok) {
        setEmails(prev => prev.filter(email => email.id !== emailId));
        
        // Clear previous toast timer if exists
        if (undoToast && undoToast.timerId) {
          clearTimeout(undoToast.timerId);
        }

        // Set new toast that will hide after 5 seconds
        const timerId = setTimeout(() => {
          setUndoToast(null);
        }, 5000);

        setUndoToast({
          emailId: emailId,
          emailSubject: emailToDelete?.subject || "Thư",
          timerId: timerId
        });

      } else {
        alert("Lỗi khi xóa email");
      }
    } catch (err) {
      alert("Lỗi kết nối máy chủ");
    }
  };

  const handleUndoDelete = async () => {
    if (!undoToast) return;
    try {
      const res = await fetch(`${API_BASE}/emails/${undoToast.emailId}/restore`, {
        method: 'PATCH',
        headers: { 'Authorization': `Bearer ${getToken()}` }
      });
      if (res.ok) {
        if (undoToast.timerId) clearTimeout(undoToast.timerId);
        setUndoToast(null);
        fetchEmails();
      } else {
        alert("Lỗi khi khôi phục email");
      }
    } catch (err) {
      alert("Lỗi kết nối máy chủ");
    }
  };

  const handleUpdateProfile = async () => {
    if (!profileForm.username) {
      alert("Tên hiển thị không được để trống");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/user/update`, {
        method: 'PATCH',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getToken()}` 
        },
        body: JSON.stringify(profileForm)
      });
      const data = await res.json();
      if (res.ok) {
        setUser({ ...user, username: data.username });
        setSettingsModal(null);
        alert("Cập nhật thành công");
      } else {
        alert(data.detail || "Lỗi cập nhật");
      }
    } catch (err) {
      alert("Lỗi kết nối máy chủ");
    }
  };

  const handleChangePassword = async () => {
    if (passwordForm.new_password !== passwordForm.confirm_password) {
      alert("Mật khẩu xác nhận không khớp");
      return;
    }
    if (passwordForm.new_password.length < 6) {
      alert("Mật khẩu mới phải có ít nhất 6 ký tự");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/user/change-password`, {
        method: 'PATCH',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getToken()}` 
        },
        body: JSON.stringify(passwordForm)
      });
      const data = await res.json();
      if (res.ok) {
        setSettingsModal(null);
        setPasswordForm({ old_password: '', new_password: '', confirm_password: '' });
        alert("Đổi mật khẩu thành công");
      } else {
        alert(data.detail || "Lỗi đổi mật khẩu");
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
        alert("Đã nhận tệp! Đang tiến hành phân loại...");
        fetchStats();
      }
    } catch (err) {
      alert("Lỗi tải lên");
    }
  };

  const getSubcategoryBadgeStyle = (sub) => {
    if (!sub) return null;
    const s = sub.toLowerCase();
    switch (s) {
      case 'facebook': return { backgroundColor: '#e8f0fe', color: '#1a73e8', border: '1px solid #1a73e8' };
      case 'instagram': return { backgroundColor: '#fce8e6', color: '#d93025', border: '1px solid #d93025' };
      case 'twitter': return { backgroundColor: '#e8f0fe', color: '#1da1f2', border: '1px solid #1da1f2' };
      case 'linkedin': return { backgroundColor: '#e8f0fe', color: '#0077b5', border: '1px solid #0077b5' };
      case 'tiktok': return { backgroundColor: '#f1f1f1', color: '#010101', border: '1px solid #010101' };
      case 'shopee': return { backgroundColor: '#feeedb', color: '#ee4d2d', border: '1px solid #ee4d2d' };
      case 'lazada': return { backgroundColor: '#f3e8fd', color: '#5f27cd', border: '1px solid #5f27cd' };
      case 'tiki': return { backgroundColor: '#e8f0fe', color: '#00adef', border: '1px solid #00adef' };
      case 'grab': return { backgroundColor: '#e6f4ea', color: '#137333', border: '1px solid #137333' };
      case 'momo': return { backgroundColor: '#fce8f3', color: '#d01270', border: '1px solid #d01270' };
      default: {
        let hash = 0;
        for (let i = 0; i < s.length; i++) {
          hash = s.charCodeAt(i) + ((hash << 5) - hash);
        }
        const hue = Math.abs(hash % 360);
        return {
          backgroundColor: `hsl(${hue}, 85%, 96%)`,
          color: `hsl(${hue}, 85%, 35%)`,
          border: `1px solid hsl(${hue}, 85%, 82%)`
        };
      }
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
    { name: 'Hộp thư (Inbox)', value: stats.ham || 0, color: '#1e8e3e', subcategories: stats.subcategory_details?.inbox || {} },
    { name: 'Thư rác (Spam)', value: stats.spam || 0, color: '#d93025', subcategories: stats.subcategory_details?.spam || {} },
    { name: 'Quảng cáo (Ads)', value: stats.ads || 0, color: '#fbbc04', subcategories: stats.subcategory_details?.ads || {} },
    { name: 'Mạng xã hội (Social)', value: stats.social || 0, color: '#1a73e8', subcategories: stats.subcategory_details?.social || {} }
  ];

  if (user && user.role === 'admin') {
    const filteredUsers = allUsers.filter(u => 
      u.username.toLowerCase().includes(searchQuery.toLowerCase()) || 
      u.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.role.toLowerCase().includes(searchQuery.toLowerCase())
    );

    const adminChartData = [
      { name: 'Hộp thư (Inbox)', value: adminStats.ham || 0, color: '#1e8e3e', subcategories: adminStats.subcategory_details?.inbox || {} },
      { name: 'Thư rác (Spam)', value: adminStats.spam || 0, color: '#d93025', subcategories: adminStats.subcategory_details?.spam || {} },
      { name: 'Quảng cáo (Ads)', value: adminStats.ads || 0, color: '#fbbc04', subcategories: adminStats.subcategory_details?.ads || {} },
      { name: 'Mạng xã hội (Social)', value: adminStats.social || 0, color: '#1a73e8', subcategories: adminStats.subcategory_details?.social || {} }
    ];

    return (
      <div className="app-container">
        <div className="sidebar">
          <div style={{ padding: '16px', fontWeight: 500, fontSize: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert color="#d93025" /> Admin Panel
          </div>
          <div className={`nav-item ${adminView === 'users' ? 'active' : ''}`} onClick={() => setAdminView('users')}>
            <Users size={20} /> Quản lý User
          </div>
          <div className={`nav-item ${adminView === 'stats' ? 'active' : ''}`} onClick={() => setAdminView('stats')}>
            <BarChart2 size={20} /> Thống kê Email
          </div>
          <div style={{ marginTop: 'auto', borderTop: '1px solid var(--border-color)', padding: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: '#d93025', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px' }}>
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

        <div className="main-content" style={{ padding: '32px', overflowY: 'auto' }}>
          {adminView === 'users' ? (
            <div className="admin-users-view">
              <h2>Quản lý người dùng</h2>
              <div className="search-bar" style={{ marginTop: '20px', marginBottom: '20px', position: 'relative' }}>
                <Search size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                <input 
                  type="text" 
                  placeholder="Tìm kiếm theo username, email, role..." 
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  style={{ width: '100%', padding: '10px 10px 10px 40px', borderRadius: '8px', border: '1px solid var(--border-color)' }}
                />
              </div>
              
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>STT</th>
                    <th>Email</th>
                    <th>Username</th>
                    <th>Password</th>
                    <th>Role</th>
                    <th>Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.map((u, idx) => (
                    <tr key={u.id}>
                      <td>{idx + 1}</td>
                      <td>{u.email}</td>
                      <td>{u.username}</td>
                      <td>********</td>
                      <td>
                        <span className={`badge ${u.role === 'admin' ? 'spam-badge' : ''}`} style={u.role !== 'admin' ? {backgroundColor: '#e8f0fe', color: '#1a73e8'} : {}}>
                          {u.role.toUpperCase()}
                        </span>
                      </td>
                      <td>
                        <button className="icon-btn" onClick={() => { setEditUserModal(u); setEditUserForm({ password: '', role: u.role }); }} title="Chỉnh sửa" style={{ display: 'inline-flex' }}>
                          <Edit size={16} color="var(--primary-color)" />
                        </button>
                        <button className="icon-btn" onClick={() => handleAdminDeleteUser(u.id)} title="Xóa" style={{ display: 'inline-flex' }}>
                          <Trash2 size={16} color="var(--error)" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredUsers.length === 0 && (
                    <tr><td colSpan="6" style={{textAlign: 'center', padding: '20px'}}>Không tìm thấy người dùng</td></tr>
                  )}
                </tbody>
              </table>

              {/* Edit Modal */}
              {editUserModal && (
                <div className="settings-modal-overlay" onClick={() => setEditUserModal(null)}>
                  <div className="settings-modal" onClick={e => e.stopPropagation()}>
                    <div className="modal-header">
                      <span>Sửa thông tin: {editUserModal.email}</span>
                      <button onClick={() => setEditUserModal(null)} style={{ border: 'none', background: 'none', color: 'white', cursor: 'pointer', fontSize: '18px' }}>×</button>
                    </div>
                    <div className="modal-body" style={{ padding: '20px' }}>
                      <div style={{ marginBottom: '15px' }}>
                        <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Đổi mật khẩu (Để trống nếu không đổi)</label>
                        <input type="password" placeholder="Mật khẩu mới" value={editUserForm.password} onChange={e => setEditUserForm({ ...editUserForm, password: e.target.value })} />
                      </div>
                      <div>
                        <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Quyền hạn (Role)</label>
                        <select value={editUserForm.role} onChange={e => setEditUserForm({ ...editUserForm, role: e.target.value })} style={{ width: '100%', marginTop: '10px' }}>
                          <option value="user">USER</option>
                          <option value="admin">ADMIN</option>
                        </select>
                      </div>
                    </div>
                    <div className="modal-footer" style={{ borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                      <button onClick={() => setEditUserModal(null)} style={{ padding: '8px 16px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>Hủy</button>
                      <button className="send-btn" onClick={handleAdminUpdateUser}>Lưu</button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="admin-stats-view">
              <h2>Thống kê Email toàn hệ thống</h2>
              <div className="card" style={{ marginTop: '20px' }}>
                <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', marginBottom: '24px' }}>
                  <div className="stat-item">
                    <div className="stat-label">Tổng số email đã xử lý</div>
                    <div className="stat-value">{adminStats.total.toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Hộp thư</div>
                    <div className="stat-value" style={{ color: '#1e8e3e', fontSize: '24px' }}>{(adminStats.ham || 0).toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Thư rác</div>
                    <div className="stat-value" style={{ color: '#d93025', fontSize: '24px' }}>{(adminStats.spam || 0).toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Quảng cáo</div>
                    <div className="stat-value" style={{ color: '#fbbc04', fontSize: '24px' }}>{(adminStats.ads || 0).toLocaleString()}</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-label">Mạng xã hội</div>
                    <div className="stat-value" style={{ color: '#1a73e8', fontSize: '24px' }}>{(adminStats.social || 0).toLocaleString()}</div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '24px' }}>
                  <div className="chart-container" style={{ flex: 1, height: '300px' }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={adminChartData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5} dataKey="value">
                          {adminChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip />
                        <Legend />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="chart-container" style={{ flex: 1, height: '300px' }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={adminChartData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="name" />
                        <YAxis />
                        <Tooltip content={<CustomTooltip />} />
                        <Bar dataKey="value">
                          {adminChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </div>
          )}
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
          onClick={() => { setView('mailbox'); setFolder('inbox'); setSelectedEmail(null); setSubcategory('all'); setPage(1); }}>
          <Mail size={20} /> Hộp thư đến
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'ads' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('ads'); setSelectedEmail(null); setSubcategory('all'); setPage(1); }}>
          <MailIcon size={20} /> Quảng cáo
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'social' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('social'); setSelectedEmail(null); setSubcategory('all'); setPage(1); }}>
          <MailIcon size={20} /> Mạng xã hội
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'spam' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('spam'); setSelectedEmail(null); setSubcategory('all'); setPage(1); }}>
          <ShieldAlert size={20} /> Thư rác
        </div>

        <div className={`nav-item ${view === 'mailbox' && folder === 'sent' ? 'active' : ''}`}
          onClick={() => { setView('mailbox'); setFolder('sent'); setSelectedEmail(null); setSubcategory('all'); setPage(1); }}>
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
            <div className="settings-wrapper">
              <button className="settings-btn" onClick={() => setShowSettingsMenu(!showSettingsMenu)}>
                <Settings size={18} />
              </button>
              {showSettingsMenu && (
                <div className="settings-dropdown">
                  <button className="settings-menu-item" onClick={() => { setShowSettingsMenu(false); setSettingsModal('profile'); }}>
                    <User size={16} /> Sửa thông tin
                  </button>
                  <button className="settings-menu-item" onClick={() => { setShowSettingsMenu(false); setSettingsModal('password'); }}>
                    <Lock size={16} /> Đổi mật khẩu
                  </button>
                </div>
              )}
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

            {!selectedEmail && (folder === 'social' || folder === 'ads') && (
              <div className="subcategory-tabs">
                <button 
                  className={`subcategory-tab ${subcategory === 'all' ? 'active' : ''}`} 
                  onClick={() => { setSubcategory('all'); setPage(1); }}
                >
                  Tất cả
                </button>
                {availableSubcategories.map(sub => (
                  <button 
                    key={sub} 
                    className={`subcategory-tab ${subcategory === sub ? 'active' : ''}`} 
                    onClick={() => { setSubcategory(sub); setPage(1); }}
                  >
                    {sub.charAt(0).toUpperCase() + sub.slice(1)}
                  </button>
                ))}
              </div>
            )}

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
                        <span className="time-text">{formatEmailTime(email.created_at)}</span>
                        <button className="delete-btn" onClick={(e) => handleDeleteEmail(e, email.id)} title="Xóa">
                          <Trash2 size={16} />
                        </button>
                      </div>
                      {email.category === 'spam' && folder !== 'spam' && <span className="badge spam-badge">SPAM</span>}
                      {email.category === 'ads' && folder !== 'ads' && <span className="badge" style={{backgroundColor: '#fbbc04', color: 'white'}}>ADS</span>}
                      {email.subcategory && (
                        <span className="badge subcategory-badge" style={getSubcategoryBadgeStyle(email.subcategory)}>
                          {email.subcategory.toUpperCase()}
                        </span>
                      )}
                    </div>
                  ))}
                  {emails.filter(e => folder === 'sent' ? true : e.category === folder).length === 0 && (
                    <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                      Không có thư!
                    </div>
                  )}
                  {emails.length > 0 && (
                    <div className="pagination-bar" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '15px', padding: '16px', borderTop: '1px solid var(--border-color)', backgroundColor: 'var(--white)' }}>
                      <button 
                        className="btn" 
                        disabled={page === 1} 
                        onClick={() => setPage(prev => Math.max(prev - 1, 1))}
                        style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid var(--border-color)', background: page === 1 ? '#f5f5f5' : 'var(--white)', cursor: page === 1 ? 'not-allowed' : 'pointer', fontSize: '13px' }}
                      >
                        Trang trước
                      </button>
                      <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Trang {page}</span>
                      <button 
                        className="btn" 
                        disabled={emails.length < 50} 
                        onClick={() => setPage(prev => prev + 1)}
                        style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid var(--border-color)', background: emails.length < 50 ? '#f5f5f5' : 'var(--white)', cursor: emails.length < 50 ? 'not-allowed' : 'pointer', fontSize: '13px' }}
                      >
                        Trang sau
                      </button>
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
              <p>Kéo và thả file CSV vào đây để phân loại</p>
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
                    <Tooltip content={<CustomTooltip />} />
                    <Bar dataKey="value">
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Bar>
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

      {/* Settings Modals */}
      {settingsModal === 'profile' && (
        <div className="settings-modal-overlay" onClick={() => setSettingsModal(null)}>
          <div className="settings-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span>Sửa thông tin</span>
              <button onClick={() => setSettingsModal(null)} style={{ border: 'none', background: 'none', color: 'white', cursor: 'pointer', fontSize: '18px' }}>×</button>
            </div>
            <div className="modal-body" style={{ padding: '20px' }}>
              <div style={{ marginBottom: '15px' }}>
                <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Email (Không thể thay đổi)</label>
                <input disabled value={user.email} style={{ background: '#f5f5f5', color: '#888' }} />
              </div>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Tên hiển thị</label>
                <input value={profileForm.username} onChange={e => setProfileForm({ ...profileForm, username: e.target.value })} />
              </div>
            </div>
            <div className="modal-footer" style={{ borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button onClick={() => setSettingsModal(null)} style={{ padding: '8px 16px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>Hủy</button>
              <button className="send-btn" onClick={handleUpdateProfile}>Lưu</button>
            </div>
          </div>
        </div>
      )}

      {settingsModal === 'password' && (
        <div className="settings-modal-overlay" onClick={() => setSettingsModal(null)}>
          <div className="settings-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span>Đổi mật khẩu</span>
              <button onClick={() => setSettingsModal(null)} style={{ border: 'none', background: 'none', color: 'white', cursor: 'pointer', fontSize: '18px' }}>×</button>
            </div>
            <div className="modal-body" style={{ padding: '20px' }}>
              <div>
                <input type="password" placeholder="Mật khẩu cũ" value={passwordForm.old_password} onChange={e => setPasswordForm({ ...passwordForm, old_password: e.target.value })} />
              </div>
              <div>
                <input type="password" placeholder="Mật khẩu mới" value={passwordForm.new_password} onChange={e => setPasswordForm({ ...passwordForm, new_password: e.target.value })} />
              </div>
              <div>
                <input type="password" placeholder="Xác nhận mật khẩu mới" value={passwordForm.confirm_password} onChange={e => setPasswordForm({ ...passwordForm, confirm_password: e.target.value })} />
              </div>
            </div>
            <div className="modal-footer" style={{ borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button onClick={() => setSettingsModal(null)} style={{ padding: '8px 16px', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>Hủy</button>
              <button className="send-btn" onClick={handleChangePassword}>Lưu</button>
            </div>
          </div>
        </div>
      )}

      {/* Undo Toast Notification */}
      {undoToast && (
        <div className="undo-toast">
          <span className="undo-toast-text">Đã xóa thư thành công.</span>
          <button className="undo-btn" onClick={handleUndoDelete}>Khôi phục</button>
        </div>
      )}
    </div>
  );
}

export default App;
