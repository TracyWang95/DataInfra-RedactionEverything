import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '../../test-utils';
import { EmptyState } from '@/components/EmptyState';

describe('EmptyState', () => {
  it('renders with title only', () => {
    render(<EmptyState title="No documents" />);
    expect(screen.getByText('No documents')).toBeInTheDocument();
  });

  it('renders title and description', () => {
    render(
      <EmptyState title="No results" description="Try a different search query" />,
    );
    expect(screen.getByText('No results')).toBeInTheDocument();
    expect(screen.getByText('Try a different search query')).toBeInTheDocument();
  });

  it('does not render description when not provided', () => {
    const { container } = render(<EmptyState title="Empty" />);
    // Only the title paragraph should exist in the text area
    const textBlock = container.querySelector('.max-w-xs');
    expect(textBlock?.querySelectorAll('p')).toHaveLength(1);
  });

  it('renders action button that fires onClick', () => {
    const handleClick = vi.fn();
    render(
      <EmptyState
        title="Nothing here"
        action={{ label: 'Create new', onClick: handleClick }}
      />,
    );
    const button = screen.getByRole('button', { name: 'Create new' });
    expect(button).toBeInTheDocument();
    button.click();
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('does not render a button when action is not provided', () => {
    render(<EmptyState title="Empty" />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders custom icon when provided', () => {
    render(
      <EmptyState
        title="Custom"
        icon={<span data-testid="custom-icon">ICON</span>}
      />,
    );
    expect(screen.getByTestId('custom-icon')).toBeInTheDocument();
  });

  it('renders default SVG icon when no icon prop given', () => {
    const { container } = render(<EmptyState title="Default icon" />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
});
