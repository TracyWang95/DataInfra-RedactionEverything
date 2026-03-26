import React from 'react';

type UnderDevelopmentProps = {
  title: string;
  description?: string;
};

export const UnderDevelopment: React.FC<UnderDevelopmentProps> = ({ title, description }) => {
  return (
    <div className="h-full min-h-0 min-w-0 overflow-auto overscroll-contain p-4 sm:p-6">
      <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
        <div className="mx-auto mb-4 h-12 w-12 rounded-full bg-gray-100 flex items-center justify-center text-gray-500">
          <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l2 2m6-2a8 8 0 11-16 0 8 8 0 0116 0z" />
          </svg>
        </div>
        <h2 className="text-lg font-semibold text-gray-900">{title}（待开发）</h2>
        <p className="mt-2 text-sm text-gray-500">
          {description || '该功能正在开发中，敬请期待。'}
        </p>
      </div>
    </div>
  );
};

export default UnderDevelopment;
