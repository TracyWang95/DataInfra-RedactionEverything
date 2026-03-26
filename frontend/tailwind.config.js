/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 主色调：深蓝 - 专业、可信赖
        primary: {
          50: '#f0f5fa',
          100: '#dae5f2',
          200: '#b8cde6',
          300: '#8badd4',
          400: '#5a88be',
          500: '#3d6ba3',
          600: '#1E3A5F', // 主色
          700: '#1a3352',
          800: '#162b45',
          900: '#12233a',
          950: '#0c1726',
        },
        // 强调色：金色 - 高亮敏感信息
        accent: {
          50: '#fefcf3',
          100: '#fdf8e1',
          200: '#faefbc',
          300: '#f6e28d',
          400: '#f0d05c',
          500: '#D4AF37', // 金色
          600: '#c49b25',
          700: '#a37d1f',
          800: '#866420',
          900: '#70531f',
          950: '#412d0e',
        },
        // 实体类型颜色
        entity: {
          person: '#F59E0B',    // 人名 - 琥珀色
          org: '#3B82F6',       // 机构 - 蓝色
          idcard: '#EF4444',    // 身份证 - 红色
          phone: '#10B981',     // 电话 - 绿色
          address: '#8B5CF6',   // 地址 - 紫色
          bankcard: '#EC4899',  // 银行卡 - 粉色
          casenumber: '#6366F1', // 案号 - 靛蓝
          date: '#14B8A6',      // 日期 - 青色
          money: '#F97316',     // 金额 - 橙色
          custom: '#6B7280',    // 自定义 - 灰色
        },
      },
      fontFamily: {
        // 法律文书感的字体
        serif: ['Source Han Serif SC', 'Noto Serif SC', 'SimSun', 'serif'],
        // UI 界面字体
        sans: ['Inter', 'Source Han Sans SC', 'Microsoft YaHei', 'sans-serif'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
