/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class', 'class'],
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
  	extend: {
  		colors: {
  			primary: {
  				'50': '#f0f5fa',
  				'100': '#dae5f2',
  				'200': '#b8cde6',
  				'300': '#8badd4',
  				'400': '#5a88be',
  				'500': '#3d6ba3',
  				'600': '#1E3A5F',
  				'700': '#1a3352',
  				'800': '#162b45',
  				'900': '#12233a',
  				'950': '#0c1726'
  			},
  			accent: {
  				'50': '#fefcf3',
  				'100': '#fdf8e1',
  				'200': '#faefbc',
  				'300': '#f6e28d',
  				'400': '#f0d05c',
  				'500': '#D4AF37',
  				'600': '#c49b25',
  				'700': '#a37d1f',
  				'800': '#866420',
  				'900': '#70531f',
  				'950': '#412d0e'
  			},
  			entity: {
  				person: '#F59E0B',
  				org: '#3B82F6',
  				idcard: '#EF4444',
  				phone: '#10B981',
  				address: '#8B5CF6',
  				bankcard: '#EC4899',
  				casenumber: '#6366F1',
  				date: '#14B8A6',
  				money: '#F97316',
  				custom: '#6B7280'
  			},
  			sidebar: {
  				DEFAULT: 'hsl(var(--sidebar-background))',
  				foreground: 'hsl(var(--sidebar-foreground))',
  				primary: 'hsl(var(--sidebar-primary))',
  				'primary-foreground': 'hsl(var(--sidebar-primary-foreground))',
  				accent: 'hsl(var(--sidebar-accent))',
  				'accent-foreground': 'hsl(var(--sidebar-accent-foreground))',
  				border: 'hsl(var(--sidebar-border))',
  				ring: 'hsl(var(--sidebar-ring))'
  			}
  		},
  		fontFamily: {
  			serif: [
  				'Source Han Serif SC',
  				'Noto Serif SC',
  				'SimSun',
  				'serif'
  			],
  			sans: [
  				'Inter',
  				'Source Han Sans SC',
  				'Microsoft YaHei',
  				'sans-serif'
  			]
  		},
  		animation: {
  			'fade-in': 'fadeIn 0.3s ease-in-out',
  			'slide-up': 'slideUp 0.3s ease-out',
  			'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite'
  		},
  		keyframes: {
  			fadeIn: {
  				'0%': {
  					opacity: '0'
  				},
  				'100%': {
  					opacity: '1'
  				}
  			},
  			slideUp: {
  				'0%': {
  					transform: 'translateY(10px)',
  					opacity: '0'
  				},
  				'100%': {
  					transform: 'translateY(0)',
  					opacity: '1'
  				}
  			}
  		}
  	}
  },
  plugins: [],
}
